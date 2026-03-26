import asyncio
import json
import logging
from pathlib import Path
from dataclasses import dataclass

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    UserMessage,
    SystemMessage,
    ResultMessage,
    StreamEvent,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
    ThinkingBlock,
)

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    success: bool
    session_id: str | None = None
    error: str | None = None
    cost_usd: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class AgentSession:
    """Wraps a ClaudeSDKClient for a single item's agent run."""

    def __init__(
        self,
        worktree_path: Path,
        system_prompt: str,
        model: str | None = None,
        on_message=None,
        on_tool_use=None,
        on_thinking=None,
        on_complete=None,
        on_error=None,
        on_clarify=None,
        on_create_todo=None,
        on_set_commit_message=None,
        on_request_command=None,
        mcp_servers: str | None = None,
        mcp_enabled: bool = False,
        plugins: list[dict] | None = None,
        allowed_commands: list[str] | None = None,
    ):
        self.worktree_path = worktree_path
        self.system_prompt = system_prompt
        self.model = model
        self.allowed_commands = allowed_commands or []
        self.on_message = on_message        # async callback(text: str)
        self.on_tool_use = on_tool_use      # async callback(tool_name: str, input: dict)
        self.on_thinking = on_thinking      # async callback(thinking: str)
        self.on_complete = on_complete      # async callback(result: AgentResult)
        self.on_error = on_error            # async callback(error: str)
        self.on_clarify = on_clarify        # async callback(prompt: str, choices: list|None) -> str
        self.on_create_todo = on_create_todo  # async callback(title: str, description: str) -> dict
        self.on_set_commit_message = on_set_commit_message  # async callback(message: str) -> str
        self.on_request_command = on_request_command  # async callback(command: str, reason: str) -> str
        self.mcp_servers = mcp_servers      # JSON string of MCP server configurations from agent config
        self.mcp_enabled = mcp_enabled      # Whether MCP is enabled from agent config
        self.plugins = plugins              # List of plugin configs: [{"type": "local", "path": "..."}]
        self.client: ClaudeSDKClient | None = None
        self._task: asyncio.Task | None = None
        self._cancelled = False
        self.current_session_id: str | None = None

    async def start(self, prompt: str, attachments: list[dict] | None = None, resume_session_id: str | None = None) -> None:
        """Start the agent with a prompt and optional image attachments."""
        from .clarification import create_clarification_server
        from .todo import create_todo_server
        from .commit_message import create_commit_message_server

        mcp_servers = {}
        if self.on_clarify:
            mcp_servers["clarification"] = create_clarification_server(self.on_clarify)
        if self.on_create_todo:
            mcp_servers["todo"] = create_todo_server(self.on_create_todo)
        if self.on_set_commit_message:
            mcp_servers["commit_message"] = create_commit_message_server(self.on_set_commit_message)
        if self.on_request_command:
            from .command_access import create_command_access_server
            mcp_servers["command_access"] = create_command_access_server(self.on_request_command)

        # Load MCP servers from agent configuration (database)
        if self.mcp_enabled and self.mcp_servers:
            try:
                agent_mcp_servers = json.loads(self.mcp_servers)
                mcp_servers.update(agent_mcp_servers)
                logger.info(f"Loaded {len(agent_mcp_servers)} MCP servers from agent configuration")
            except Exception as e:
                logger.warning(f"Failed to parse MCP servers from agent config: {e}")

        # Load external MCP servers from mcp-config.json
        mcp_config_path = self.worktree_path / "mcp-config.json"
        if mcp_config_path.exists():
            try:
                with open(mcp_config_path, 'r') as f:
                    external_config = json.load(f)
                    external_servers = external_config.get("mcpServers", {})
                    mcp_servers.update(external_servers)
                    logger.info(f"Loaded {len(external_servers)} external MCP servers from config")
            except Exception as e:
                logger.warning(f"Failed to load MCP config: {e}")

        # Ensure agent knows to work in the worktree directory
        cwd_note = f"\n\nIMPORTANT: Your working directory is {self.worktree_path}. All file operations must be within this directory."
        commit_note = (
            "\n\nIMPORTANT: When you have finished your task, you MUST call the "
            "set_commit_message tool with a concise commit message summarizing what you did. "
            "Use conventional style: start with a verb (Add, Fix, Update, Refactor, Remove). "
            "This is required — do not skip it."
        )
        command_note = (
            "\n\nIf a shell command is blocked, use the request_command_access tool "
            "to ask the user for permission. Provide the command name and reason."
        )
        full_system_prompt = (self.system_prompt or "") + cwd_note + commit_note + command_note

        # Configure allowed MCP tools
        allowed_tools = []
        if "clarification" in mcp_servers:
            allowed_tools.append("mcp__clarification__ask_user")
        if "todo" in mcp_servers:
            allowed_tools.append("mcp__todo__create_todo")
        if "commit_message" in mcp_servers:
            allowed_tools.append("mcp__commit_message__set_commit_message")
        if "command_access" in mcp_servers:
            allowed_tools.append("mcp__command_access__request_command_access")

        # Allow all tools from external MCP servers (using wildcard for each server)
        for server_name, server_config in mcp_servers.items():
            if server_name not in ["clarification", "todo", "commit_message", "command_access"]:  # Skip our built-in servers
                allowed_tools.append(f"mcp__{server_name}__*")
                logger.info(f"Allowing all tools from external MCP server: {server_name}")

        # Build plugins list from configured plugin paths
        plugins = None
        if self.plugins:
            plugins = []
            for plugin_config in self.plugins:
                plugin_path = plugin_config.get("path", "")
                if plugin_path:
                    plugins.append({"type": "local", "path": plugin_path})
                    logger.info(f"Loading plugin from: {plugin_path}")

        # Session ID capture hook — always registered so we can resume on restart
        from claude_agent_sdk import HookMatcher

        async def capture_session_id(hook_input, tool_use_id, context):
            sid = hook_input.get("session_id") if isinstance(hook_input, dict) else None
            if sid:
                self.current_session_id = sid
            return {}

        hooks = {
            "PreToolUse": [
                HookMatcher(hooks=[capture_session_id]),
            ]
        }

        # Command filter hook for allowed bash commands
        if self.allowed_commands:
            allowed_tools.append("Bash")
            from .command_filter import make_command_filter_hook
            hooks["PreToolUse"].append(
                HookMatcher(
                    matcher="Bash",
                    hooks=[make_command_filter_hook(self.allowed_commands, session=self)],
                )
            )

        options = ClaudeAgentOptions(
            cwd=self.worktree_path,
            system_prompt=full_system_prompt,
            model=self.model,
            permission_mode="acceptEdits",  # More targeted than bypassPermissions
            mcp_servers=mcp_servers if mcp_servers else None,
            allowed_tools=allowed_tools if allowed_tools else None,
            add_dirs=[str(self.worktree_path)],
            thinking={"type": "enabled", "budget_tokens": 10000},
            plugins=plugins if plugins else None,
            hooks=hooks,
        )

        if resume_session_id:
            options.resume = resume_session_id
            options.continue_conversation = True

        self.client = ClaudeSDKClient(options=options)
        await self.client.connect()
        self._task = asyncio.create_task(self._receive_loop())

        # Copy attachments into worktree and reference in prompt
        if attachments:
            import shutil
            attachment_refs = []
            for attachment in attachments:
                try:
                    asset_path = Path(attachment["asset_path"])
                    if asset_path.exists():
                        dest = self.worktree_path / attachment["filename"]
                        shutil.copy2(asset_path, dest)
                        attachment_refs.append(str(dest))
                        logger.info(f"Copied attachment to worktree: {attachment['filename']}")
                except Exception as e:
                    logger.warning(f"Failed to copy attachment {attachment.get('filename', 'unknown')}: {e}")
            if attachment_refs:
                prompt += "\n\nAttached reference images (use Read tool to view):\n"
                prompt += "\n".join(f"- {ref}" for ref in attachment_refs)

        await self.client.query(prompt)

    async def _receive_loop(self) -> None:
        """Process messages from the agent."""
        # Capture client reference so finally block can disconnect even if
        # on_complete callback nulls self.client (e.g., via cancel())
        client_ref = self.client
        try:
            async for message in self.client.receive_messages():
                if self._cancelled:
                    break

                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            if self.on_message:
                                await self.on_message(block.text)
                        elif isinstance(block, ThinkingBlock):
                            if self.on_thinking and block.thinking:
                                await self.on_thinking(block.thinking)
                        elif isinstance(block, ToolUseBlock):
                            if self.on_tool_use:
                                await self.on_tool_use(block.name, block.input)

                elif isinstance(message, ResultMessage):
                    # Capture session_id
                    if message.session_id:
                        self.current_session_id = message.session_id

                    # Extract token usage from the usage dict
                    input_tokens = None
                    output_tokens = None
                    total_tokens = None

                    usage = message.usage or {}
                    if usage:
                        input_tokens = usage.get("input_tokens") or usage.get("input_token_count")
                        output_tokens = usage.get("output_tokens") or usage.get("output_token_count")
                        total_tokens = usage.get("total_tokens") or usage.get("total_token_count")

                    # Calculate total if not provided but components are
                    if total_tokens is None and input_tokens is not None and output_tokens is not None:
                        total_tokens = input_tokens + output_tokens

                    result = AgentResult(
                        success=not message.is_error,
                        session_id=message.session_id,
                        cost_usd=message.total_cost_usd,
                        error=message.result if message.is_error else None,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        total_tokens=total_tokens,
                    )
                    if self.on_complete:
                        await self.on_complete(result)
                    return

                elif isinstance(message, SystemMessage):
                    # Log system messages (progress, etc.)
                    if self.on_message and hasattr(message, 'content'):
                        text = str(message.content) if message.content else ""
                        if text:
                            await self.on_message(f"[system] {text}")

        except Exception as e:
            logger.exception("Agent session error")
            if self.on_error:
                await self.on_error(str(e))
        finally:
            # Clean up client connection — use captured reference since
            # self.client may have been set to None by cancel()
            self.client = None
            if client_ref:
                try:
                    await client_ref.disconnect()
                except Exception:
                    pass
                # Fallback: directly kill the subprocess if it's still alive
                try:
                    transport = getattr(client_ref, '_transport', None)
                    process = getattr(transport, '_process', None) if transport else None
                    if process and process.returncode is None:
                        logger.warning("Subprocess still alive after disconnect, terminating")
                        process.terminate()
                except Exception:
                    pass

    async def send_message(self, text: str) -> None:
        """Send a follow-up message to the agent (e.g., clarification response)."""
        if self.client:
            await self.client.query(text)

    async def cancel(self) -> None:
        """Cancel the running agent."""
        self._cancelled = True

        # Disconnect the client FIRST to terminate the subprocess,
        # before cancelling the receive loop task.
        # This ensures the subprocess is killed even if task cancellation
        # interferes with cleanup in the finally block.
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.client = None

        # Then cancel the receive loop task
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    async def disconnect(self) -> None:
        """Clean disconnect."""
        if self.client:
            await self.client.disconnect()
