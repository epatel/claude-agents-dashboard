"""Kimi Agent SDK session — the dashboard's first non-Claude runtime (experimental).

Drives one item's agent run through the in-process Kimi Agent SDK
(`kimi-agent-sdk` on PyPI, which embeds the `kimi-cli` runtime) instead of the
Claude Agent SDK. Selected by model id: anything starting with ``kimi-`` (see
`profiles.is_kimi_model`); such models are only offered in the UI when the
server runs with --experimental.

First-cut scope (deliberately mirrors the lean Ollama feature set):

- ``yolo=True`` — Kimi's own approval requests are auto-approved. The
  dashboard's per-command permission hooks are Claude-SDK constructs and do
  not apply here.
- No dashboard MCP tool servers, plugins, chrome, or graphify — so agents
  cannot call ``set_commit_message``/``ask_user``; the merge path falls back
  to its default commit message and clarification is unavailable.
- No pause/resume: ``current_session_id`` stays None, so a paused item
  restarts from scratch (the SDK's ``Session.resume`` can lift this later).
- The dashboard system prompt is prepended to the user prompt — the SDK has
  no separate system-prompt input (an ``agent_file`` could carry it later).

Requires ``KIMI_API_KEY`` (and optionally ``KIMI_BASE_URL``) in the server
environment. The SDK is imported lazily so the dashboard runs without it
installed; starting a Kimi session without the package reports a clear error.
"""

import asyncio
import json
import logging
from pathlib import Path

from .base import AbstractAgentSession, AgentResult

logger = logging.getLogger(__name__)

KIMI_SDK_INSTALL_HINT = (
    "Kimi Agent SDK is not installed in the dashboard environment. "
    "Install it with: pip install kimi-agent-sdk (requires Python >= 3.12), "
    "and set KIMI_API_KEY in the server environment."
)


def _tool_call_input(tool_call) -> dict:
    """Extract a plain dict of arguments from a kosong ToolCall."""
    function = getattr(tool_call, "function", None)
    if isinstance(function, dict):
        arguments = function.get("arguments")
    else:
        arguments = getattr(function, "arguments", None)
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except Exception:
            arguments = {"raw": arguments}
    return arguments if isinstance(arguments, dict) else {}


def _tool_call_name(tool_call) -> str:
    function = getattr(tool_call, "function", None)
    if isinstance(function, dict):
        return function.get("name") or "unknown"
    return getattr(function, "name", None) or "unknown"


class KimiAgentSession(AbstractAgentSession):
    """Wraps the Kimi Agent SDK for a single item's agent run."""

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
        item_id: str | None = None,
    ):
        self.worktree_path = worktree_path
        self.system_prompt = system_prompt
        self.model = model
        self.on_message = on_message        # async callback(text: str)
        self.on_tool_use = on_tool_use      # async callback(tool_name: str, input: dict)
        self.on_thinking = on_thinking      # async callback(thinking: str)
        self.on_complete = on_complete      # async callback(result: AgentResult)
        self.on_error = on_error            # async callback(error: str)
        self.item_id = item_id
        self._task: asyncio.Task | None = None
        self._cancelled = False
        self.current_session_id: str | None = None

    async def start(self, prompt: str, attachments: list[dict] | None = None,
                    resume_session_id: str | None = None) -> None:
        """Start the agent run as a background task (mirrors ClaudeAgentSession)."""
        if resume_session_id:
            logger.info(
                "KimiAgentSession does not support resume yet — starting fresh "
                f"(ignored session_id {resume_session_id})"
            )
        if attachments:
            from .session import build_attachment_prompt
            attachment_note = build_attachment_prompt(attachments)
            if attachment_note:
                prompt = f"{prompt}\n\n{attachment_note}"
        if self.system_prompt:
            prompt = (
                f"{self.system_prompt}\n\n"
                f"IMPORTANT: Your working directory is {self.worktree_path}. "
                "All file operations must be within this directory.\n\n"
                f"--- Task ---\n{prompt}"
            )
        self._task = asyncio.create_task(self._run(prompt))

    async def _run(self, full_prompt: str) -> None:
        try:
            try:
                from kaos.path import KaosPath
                from kimi_agent_sdk import prompt as kimi_prompt
            except ImportError:
                logger.error("kimi-agent-sdk import failed", exc_info=True)
                if self.on_error:
                    await self.on_error(KIMI_SDK_INSTALL_HINT)
                return

            logger.info(f"Kimi mode: starting Kimi Agent SDK run for model {self.model}")
            async for message in kimi_prompt(
                full_prompt,
                work_dir=KaosPath(str(self.worktree_path)),
                model=self.model,
                yolo=True,
            ):
                if self._cancelled:
                    return
                if getattr(message, "role", None) != "assistant":
                    continue  # tool-result messages; the call itself is reported below
                text = message.extract_text()
                if text and self.on_message:
                    await self.on_message(text)
                for tool_call in message.tool_calls or []:
                    if self.on_tool_use:
                        await self.on_tool_use(
                            _tool_call_name(tool_call), _tool_call_input(tool_call)
                        )

            if self._cancelled:
                return
            if self.on_complete:
                await self.on_complete(AgentResult(success=True))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if self._cancelled:
                return
            logger.exception(f"Kimi agent run failed for item {self.item_id}")
            if self.on_error:
                await self.on_error(str(e))

    async def cancel(self) -> None:
        """Stop the run; the SDK's RunCancelled surfaces as task cancellation."""
        self._cancelled = True
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
