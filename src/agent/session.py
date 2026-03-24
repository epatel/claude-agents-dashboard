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
    ):
        self.worktree_path = worktree_path
        self.system_prompt = system_prompt
        self.model = model
        self.on_message = on_message      # async callback(text: str)
        self.on_tool_use = on_tool_use    # async callback(tool_name: str, input: dict)
        self.on_thinking = on_thinking    # async callback(thinking: str)
        self.on_complete = on_complete    # async callback(result: AgentResult)
        self.on_error = on_error          # async callback(error: str)
        self.on_clarify = on_clarify      # async callback(prompt: str, choices: list|None) -> str
        self.client: ClaudeSDKClient | None = None
        self._task: asyncio.Task | None = None
        self._cancelled = False

    async def start(self, prompt: str, resume_session_id: str | None = None) -> None:
        """Start the agent with a prompt."""
        from .clarification import create_clarification_server

        mcp_servers = {}
        if self.on_clarify:
            mcp_servers["clarification"] = create_clarification_server(self.on_clarify)

        # Ensure agent knows to work in the worktree directory
        cwd_note = f"\n\nIMPORTANT: Your working directory is {self.worktree_path}. All file operations must be within this directory."
        full_system_prompt = (self.system_prompt or "") + cwd_note

        options = ClaudeAgentOptions(
            cwd=self.worktree_path,
            system_prompt=full_system_prompt,
            model=self.model,
            permission_mode="bypassPermissions",
            mcp_servers=mcp_servers if mcp_servers else None,
            add_dirs=[str(self.worktree_path)],
            thinking={"type": "enabled", "budget_tokens": 10000},
        )

        if resume_session_id:
            options.resume = resume_session_id
            options.continue_conversation = True

        self.client = ClaudeSDKClient(options=options)
        await self.client.connect()
        self._task = asyncio.create_task(self._receive_loop())
        await self.client.query(prompt)

    async def _receive_loop(self) -> None:
        """Process messages from the agent."""
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
                    result = AgentResult(
                        success=not message.is_error,
                        session_id=message.session_id,
                        cost_usd=message.total_cost_usd,
                        error=message.result if message.is_error else None,
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

    async def send_message(self, text: str) -> None:
        """Send a follow-up message to the agent (e.g., clarification response)."""
        if self.client:
            await self.client.query(text)

    async def cancel(self) -> None:
        """Cancel the running agent."""
        self._cancelled = True
        if self.client:
            try:
                await self.client.interrupt()
            except Exception:
                pass
            await self.client.disconnect()
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
