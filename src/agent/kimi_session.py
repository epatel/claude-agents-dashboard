"""Kimi agent session over ACP — the dashboard's first non-Claude runtime (experimental).

Drives one item's agent run by spawning ``kimi acp`` (the Kimi Code CLI as an
Agent Client Protocol server, CLI >= 0.27.0) via ``kimi_agent_sdk.acp`` and
streaming its session updates. The ACP client is stdlib-only — it targets
whatever ``kimi`` binary is on PATH and does NOT pin a ``kimi-cli`` version
the way the in-process ``kimi_agent_sdk.prompt`` API does.

Selected by model id: anything starting with ``kimi-`` (see
`profiles.is_kimi_model`); such models are only offered in the UI when the
server runs with --experimental. The model reaches the CLI via the
``KIMI_MODEL_NAME`` env var on the spawned subprocess (the ACP session API has
no model parameter).

First-cut scope (deliberately mirrors the lean Ollama feature set):

- ``yolo=True`` — Kimi's permission requests are auto-approved. The
  dashboard's per-command permission hooks are Claude-SDK constructs and do
  not apply here.
- No dashboard MCP tool servers, plugins, chrome, or graphify — so agents
  cannot call ``set_commit_message``/``ask_user``; the merge path falls back
  to its default commit message and clarification is unavailable.
- Pause/resume: the ACP session id is captured in ``current_session_id``;
  on restart the session is resumed via ACP ``session/load`` when the agent
  supports it (fresh start otherwise).
- The dashboard system prompt is prepended to the user prompt (ACP has no
  separate system-prompt input).

Auth follows the Kimi Code model: a one-time ``kimi login`` (OAuth tokens
stored and refreshed by the CLI) is enough; ``KIMI_API_KEY`` /
``KIMI_BASE_URL`` env vars are the headless alternative. The SDK package is
imported lazily so the dashboard runs without it installed; starting a Kimi
session without it reports a clear error.
"""

import asyncio
import logging
import os
from pathlib import Path

from .base import AbstractAgentSession, AgentResult

logger = logging.getLogger(__name__)

KIMI_SDK_INSTALL_HINT = (
    "Kimi Agent SDK is not installed in the dashboard environment. "
    "Install it with: pip install kimi-agent-sdk (requires Python >= 3.12) "
    "plus the Kimi Code CLI (`kimi`, >= 0.27.0) on PATH. "
    "Authenticate once with `kimi login` (OAuth, shared with the Kimi CLI) "
    "or set KIMI_API_KEY in the server environment for headless use."
)

# ACP stop reasons that are not a normal end of turn.
_ABNORMAL_STOP_REASONS = {"max_tokens", "max_turn_requests", "refusal"}


def _content_text(content) -> str:
    """Text of an ACP content block ('' for non-text blocks)."""
    return getattr(content, "text", "") or ""


def _tool_call_input(tool_call_start) -> dict:
    """Best-effort input dict for a ToolCallStart update."""
    raw = getattr(tool_call_start, "raw", None) or {}
    raw_input = raw.get("rawInput") if isinstance(raw, dict) else None
    input_dict = dict(raw_input) if isinstance(raw_input, dict) else {}
    if tool_call_start.kind:
        input_dict.setdefault("kind", tool_call_start.kind)
    return input_dict


class KimiAgentSession(AbstractAgentSession):
    """Wraps a `kimi acp` subprocess (via the SDK's ACP client) for one item's run."""

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
        self._acp_session = None
        self.current_session_id: str | None = None

    async def start(self, prompt: str, attachments: list[dict] | None = None,
                    resume_session_id: str | None = None) -> None:
        """Start the agent run as a background task (mirrors ClaudeAgentSession)."""
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
        self._task = asyncio.create_task(self._run(prompt, resume_session_id))

    async def _run(self, full_prompt: str, resume_session_id: str | None) -> None:
        try:
            try:
                from kimi_agent_sdk.acp import (
                    AcpClient,
                    AgentMessageChunk,
                    AgentThoughtChunk,
                    ToolCallStart,
                    TurnEnded,
                )
            except ImportError:
                logger.error("kimi_agent_sdk.acp import failed", exc_info=True)
                if self.on_error:
                    await self.on_error(KIMI_SDK_INSTALL_HINT)
                return

            env = dict(os.environ)
            if self.model:
                env["KIMI_MODEL_NAME"] = self.model

            logger.info(f"Kimi mode: spawning `kimi acp` for model {self.model}")
            async with await AcpClient.connect(yolo=True, env=env) as client:
                session = None
                if resume_session_id:
                    try:
                        session = await client.load_session(
                            resume_session_id, cwd=self.worktree_path
                        )
                        logger.info(f"Kimi mode: resumed ACP session {resume_session_id}")
                    except Exception as e:
                        logger.warning(
                            f"Kimi mode: could not resume session {resume_session_id} "
                            f"({e}) — starting fresh"
                        )
                if session is None:
                    session = await client.new_session(cwd=self.worktree_path)
                self._acp_session = session
                self.current_session_id = session.id

                # ACP streams partial chunks; aggregate them so the work log
                # gets message-sized entries (like ClaudeAgentSession's blocks).
                text_buf: list[str] = []
                thought_buf: list[str] = []

                async def flush() -> None:
                    if thought_buf and self.on_thinking:
                        await self.on_thinking("".join(thought_buf))
                    thought_buf.clear()
                    if text_buf and self.on_message:
                        await self.on_message("".join(text_buf))
                    text_buf.clear()

                stop_reason = None
                async for item in session.prompt(full_prompt):
                    if self._cancelled:
                        return
                    if isinstance(item, AgentMessageChunk):
                        text_buf.append(_content_text(item.content))
                    elif isinstance(item, AgentThoughtChunk):
                        thought_buf.append(_content_text(item.content))
                    elif isinstance(item, ToolCallStart):
                        await flush()
                        if self.on_tool_use:
                            await self.on_tool_use(item.title, _tool_call_input(item))
                    elif isinstance(item, TurnEnded):
                        stop_reason = item.stop_reason
                await flush()

                if self._cancelled or stop_reason == "cancelled":
                    return
                if stop_reason in _ABNORMAL_STOP_REASONS:
                    if self.on_error:
                        await self.on_error(f"Kimi run stopped early: {stop_reason}")
                    return
                if self.on_complete:
                    await self.on_complete(
                        AgentResult(success=True, session_id=self.current_session_id)
                    )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if self._cancelled:
                return
            logger.exception(f"Kimi agent run failed for item {self.item_id}")
            if self.on_error:
                await self.on_error(str(e))
        finally:
            self._acp_session = None

    async def cancel(self) -> None:
        """Stop the run: ask ACP to cancel, then tear down the task/subprocess."""
        self._cancelled = True
        if self._acp_session is not None:
            try:
                await asyncio.wait_for(self._acp_session.cancel(), timeout=5)
            except Exception:
                pass
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
