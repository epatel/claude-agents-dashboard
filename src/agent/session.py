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
    HookMatcher,
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
        on_request_tool=None,
        on_view_board=None,
        on_delete_todo=None,
        mcp_servers: str | None = None,
        mcp_enabled: bool = False,
        plugins: list[dict] | None = None,
        allowed_commands: list[str] | None = None,
        bash_yolo: bool = False,
        allowed_builtin_tools: list[str] | None = None,
    ):
        self.worktree_path = worktree_path
        self.system_prompt = system_prompt
        self.model = model
        self.allowed_commands = allowed_commands or []
        self.bash_yolo = bash_yolo
        self.allowed_builtin_tools = allowed_builtin_tools or []
        self.on_message = on_message        # async callback(text: str)
        self.on_tool_use = on_tool_use      # async callback(tool_name: str, input: dict)
        self.on_thinking = on_thinking      # async callback(thinking: str)
        self.on_complete = on_complete      # async callback(result: AgentResult)
        self.on_error = on_error            # async callback(error: str)
        self.on_clarify = on_clarify        # async callback(prompt: str, choices: list|None) -> str
        self.on_create_todo = on_create_todo  # async callback(title: str, description: str) -> dict
        self.on_set_commit_message = on_set_commit_message  # async callback(message: str) -> str
        self.on_request_command = on_request_command  # async callback(command: str, reason: str) -> str
        self.on_request_tool = on_request_tool      # async callback(tool_name: str, reason: str) -> str
        self.on_view_board = on_view_board          # async callback() -> str
        self.on_delete_todo = on_delete_todo        # async callback(item_id: str) -> str
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
            mcp_servers["todo"] = create_todo_server(self.on_create_todo, self.on_delete_todo)
        if self.on_set_commit_message:
            mcp_servers["commit_message"] = create_commit_message_server(self.on_set_commit_message)
        if self.on_request_command:
            from .command_access import create_command_access_server
            mcp_servers["command_access"] = create_command_access_server(self.on_request_command)
        if self.on_request_tool:
            from .tool_access import create_tool_access_server
            mcp_servers["tool_access"] = create_tool_access_server(self.on_request_tool)
        if self.on_view_board:
            from .board_view import create_board_view_server
            mcp_servers["board_view"] = create_board_view_server(self.on_view_board)

        # Load MCP servers from agent configuration (database)
        if self.mcp_enabled and self.mcp_servers:
            try:
                agent_mcp_servers = json.loads(self.mcp_servers)
                mcp_servers.update(agent_mcp_servers)
                logger.info(f"Loaded {len(agent_mcp_servers)} MCP servers from agent configuration")
            except Exception as e:
                logger.warning(f"Failed to parse MCP servers from agent config: {e}")

        # Ensure agent knows to work in the worktree directory
        cwd_note = f"\n\nIMPORTANT: Your working directory is {self.worktree_path}. All file operations must be within this directory."
        clarify_note = (
            "\n\nIMPORTANT: If you need to ask the user a question or need clarification, "
            "you MUST use the ask_user MCP tool (mcp__clarification__ask_user). "
            "Do NOT use ToolSearch, AskUserQuestion, or any other built-in tool to ask questions. "
            "The ask_user tool is the ONLY way to communicate with the user."
        )
        commit_note = (
            "\n\nIMPORTANT: When you have finished your task, you MUST call the "
            "set_commit_message tool with a concise commit message summarizing what you did. "
            "Use conventional style: start with a verb (Add, Fix, Update, Refactor, Remove). "
            "This is required — do not skip it."
        )
        todo_note = (
            "\n\nIMPORTANT: To create todo items on the board, you MUST use the create_todo MCP tool "
            "(mcp__todo__create_todo). Do NOT use TodoWrite, TaskCreate, or any other built-in tool "
            "for creating todos — those are internal tools that do not add items to the board. "
            "To delete a todo item, use mcp__todo__delete_todo. "
            "To see existing board items, use mcp__board_view__view_board."
        )
        command_note = (
            "\n\nIf a shell command is blocked, use the request_command_access tool "
            "to ask the user for permission. Provide the command name and reason."
        )
        tool_note = (
            "\n\nIf a built-in tool (like WebSearch or WebFetch) is blocked, use the "
            "mcp__tool_access__request_tool_access tool to ask the user for permission. "
            "Do NOT use ToolSearch to find it — call it directly."
        )
        full_system_prompt = (self.system_prompt or "") + cwd_note + clarify_note + commit_note + todo_note + command_note + tool_note

        # Configure allowed MCP tools
        allowed_tools = []
        if "clarification" in mcp_servers:
            allowed_tools.append("mcp__clarification__ask_user")
        if "todo" in mcp_servers:
            allowed_tools.append("mcp__todo__create_todo")
            allowed_tools.append("mcp__todo__delete_todo")
        if "commit_message" in mcp_servers:
            allowed_tools.append("mcp__commit_message__set_commit_message")
        if "command_access" in mcp_servers:
            allowed_tools.append("mcp__command_access__request_command_access")
        if "tool_access" in mcp_servers:
            allowed_tools.append("mcp__tool_access__request_tool_access")
        if "board_view" in mcp_servers:
            allowed_tools.append("mcp__board_view__view_board")

        # Allow all tools from external MCP servers (using wildcard for each server)
        for server_name, server_config in mcp_servers.items():
            if server_name not in ["clarification", "todo", "commit_message", "command_access", "tool_access", "board_view"]:  # Skip our built-in servers
                allowed_tools.append(f"mcp__{server_name}__*")
                logger.info(f"Allowing all tools from external MCP server: {server_name}")

        # Build plugins list from configured plugin paths
        plugins = None
        plugin_prefixes = []
        if self.plugins:
            plugins = []
            for plugin_config in self.plugins:
                plugin_path = plugin_config.get("path", "")
                if plugin_path:
                    plugins.append({"type": "local", "path": plugin_path})
                    plugin_name = Path(plugin_path).name
                    plugin_prefixes.append(f"mcp__plugin_{plugin_name}")
                    logger.info(f"Loading plugin from: {plugin_path}")

        # Always allow Bash in the tool whitelist — permission_mode and the
        # PreToolUse hook handle actual command filtering.
        allowed_tools.append("Bash")

        # Always add optional built-in tools to the whitelist — the PreToolUse
        # hook filters disabled ones and directs the agent to request access.
        from .tool_filter import OPTIONAL_TOOL_NAMES
        for tool_name in OPTIONAL_TOOL_NAMES:
            if tool_name not in allowed_tools:
                allowed_tools.append(tool_name)

        hooks = None
        hook_matchers = []

        if not self.bash_yolo and self.allowed_commands:
            from .command_filter import make_command_filter_hook
            hook_matchers.append(
                HookMatcher(
                    matcher="Bash",
                    hooks=[make_command_filter_hook(self.allowed_commands, session=self)],
                )
            )

        # Add tool filter hook for optional built-in tools
        from .tool_filter import make_tool_filter_hook
        for tool_name in OPTIONAL_TOOL_NAMES:
            hook_matchers.append(
                HookMatcher(
                    matcher=tool_name,
                    hooks=[make_tool_filter_hook(self.allowed_builtin_tools)],
                )
            )

        if hook_matchers:
            hooks = {"PreToolUse": hook_matchers}

        # Collect external MCP server prefixes (SDK wildcards don't work)
        external_mcp_prefixes = []
        for server_name, server_config in mcp_servers.items():
            if server_name not in ["clarification", "todo", "commit_message", "command_access", "tool_access", "board_view"]:
                external_mcp_prefixes.append(f"mcp__{server_name}__")

        # Build can_use_tool callback to allow plugin and external MCP tools
        # by prefix match, since SDK wildcard patterns don't work.
        can_use_tool_fn = None
        all_prefixes = plugin_prefixes + external_mcp_prefixes
        if all_prefixes:
            allowed_set = set(allowed_tools) if allowed_tools else set()
            def can_use_tool(tool_name: str) -> bool:
                if tool_name in allowed_set:
                    return True
                for prefix in all_prefixes:
                    if tool_name.startswith(prefix):
                        return True
                # Allow standard (non-MCP) tools — permission_mode handles them
                return not tool_name.startswith("mcp__")
            can_use_tool_fn = can_use_tool

        options = ClaudeAgentOptions(
            cwd=self.worktree_path,
            system_prompt=full_system_prompt,
            model=self.model,
            permission_mode="acceptEdits",  # More targeted than bypassPermissions
            mcp_servers=mcp_servers if mcp_servers else None,
            allowed_tools=allowed_tools if allowed_tools else None,
            can_use_tool=can_use_tool_fn,
            add_dirs=[str(self.worktree_path)],
            thinking={"type": "enabled", "budget_tokens": 10000},
            plugins=plugins if plugins else None,
            hooks=hooks,
            setting_sources=["project"],  # Load CLAUDE.md from target project
        )

        if resume_session_id:
            options.resume = resume_session_id
            options.continue_conversation = True

        self.client = ClaudeSDKClient(options=options)
        await self.client.connect()

        # Check MCP server status and report issues
        await self._check_mcp_status()

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

    async def _check_mcp_status(self) -> None:
        """Check MCP server connection status and report issues."""
        if not self.client:
            return
        try:
            status = await self.client.get_mcp_status()
            servers = status.get("mcpServers", [])
            for server in servers:
                name = server.get("name", "unknown")
                state = server.get("status", "unknown")
                if state in ("failed", "disconnected", "needs-auth"):
                    error_msg = server.get("error", "")
                    msg = f"MCP server '{name}' {state}"
                    if error_msg:
                        msg += f": {error_msg}"
                    logger.warning(msg)
                    if self.on_message:
                        await self.on_message(f"[warning] {msg}")
                    try:
                        from ..web.routes import add_notification
                        add_notification("error", msg, source=f"mcp:{name}")
                    except Exception:
                        pass
                elif state == "connected":
                    tools = server.get("tools", [])
                    tool_names = [t.get("name", "") for t in tools]
                    logger.info(f"MCP server '{name}' connected with {len(tools)} tools: {tool_names}")
        except Exception as e:
            logger.warning(f"Failed to check MCP status: {e}")

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
