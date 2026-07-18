"""Kimi agent session over ACP — the dashboard's first non-Claude runtime (experimental).

Drives one item's agent run by spawning ``kimi acp`` (the Kimi Code CLI as an
Agent Client Protocol server, CLI >= 0.27.0) via ``kimi_agent_sdk.acp`` and
streaming its session updates. The ACP client is stdlib-only — it targets
whatever ``kimi`` binary is on PATH and does NOT pin a ``kimi-cli`` version
the way the in-process ``kimi_agent_sdk.prompt`` API does.

Selected by model id: anything starting with ``kimi-`` (see
`profiles.is_kimi_model`) — the ids are kimi-code model *aliases* such as
``kimi-code/k3``; such models are only offered in the UI when the server runs
with --experimental. The model is selected per session via the ACP
``session/set_config_option`` request (configId "model", as flutter_kimi_sdk
does), with ``KIMI_MODEL_NAME`` on the subprocess env as a fallback.

First-cut scope (deliberately mirrors the lean Ollama feature set):

- ``yolo=True`` — Kimi's permission requests are auto-approved. The
  dashboard's per-command permission hooks are Claude-SDK constructs and do
  not apply here.
- No dashboard MCP tool servers, plugins, chrome, or graphify. Commit
  messages and clarifications still work via marked lines in the agent's
  text (no MCP needed): a ``COMMIT_MESSAGE:`` line routes to
  ``on_set_commit_message``; an ``ASK_USER:`` line ends the turn, blocks on
  ``on_clarify`` (Clarify column), and the user's answer is sent as the next
  prompt turn on the same stateful ACP session.
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
import re
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

# Commit messages travel as a marked line in the agent's text (Kimi agents
# have no set_commit_message MCP tool), parsed out before the text reaches
# the work log — same style as review_agent's DECISION parsing.
_COMMIT_MESSAGE_RE = re.compile(r"^[ \t]*COMMIT_MESSAGE:[ \t]*(\S.*?)[ \t]*$", re.MULTILINE)

_COMMIT_MESSAGE_NOTE = (
    "\n\nWhen your work is complete, end your FINAL message with a single line in "
    "exactly this format:\n"
    "COMMIT_MESSAGE: <one-line imperative summary of the change>\n"
    "This line is machine-parsed to label the merge commit. Include it exactly once, "
    "as the last line of your final message."
)


def _extract_commit_message(text: str) -> tuple[str, str | None]:
    """Split a COMMIT_MESSAGE line out of agent text.

    Returns (text without the line(s), last commit message or None).
    """
    matches = _COMMIT_MESSAGE_RE.findall(text)
    if not matches:
        return text, None
    return _COMMIT_MESSAGE_RE.sub("", text).rstrip(), matches[-1]


# Clarifications use the same marked-line protocol: ACP has no user-question
# channel, but sessions are stateful — the agent ends its turn with an
# ASK_USER line, the dashboard collects the answer (Clarify column), and the
# answer is sent as the next prompt turn on the same ACP session.
_ASK_USER_RE = re.compile(r"^[ \t]*ASK_USER:[ \t]*(\S.*?)[ \t]*$", re.MULTILINE)

_ASK_USER_NOTE = (
    "\n\nIf you need to ask the user a question before you can proceed, end your "
    "message with a single line in exactly this format and then STOP:\n"
    "ASK_USER: <your question>\n"
    "The user's answer will arrive as your next message. Use this only when "
    "genuinely blocked — otherwise make a reasonable assumption and state it."
)


def _extract_ask_user(text: str) -> tuple[str, str | None]:
    """Split an ASK_USER line out of agent text.

    Returns (text without the line(s), last question or None).
    """
    matches = _ASK_USER_RE.findall(text)
    if not matches:
        return text, None
    return _ASK_USER_RE.sub("", text).rstrip(), matches[-1]


def _content_text(content) -> str:
    """Text of an ACP content block ('' for non-text blocks)."""
    return getattr(content, "text", "") or ""


def _raw_input(update) -> dict | None:
    """The `rawInput` dict of an ACP tool-call update, or None if absent."""
    raw = getattr(update, "raw", None)
    raw_input = raw.get("rawInput") if isinstance(raw, dict) else None
    return dict(raw_input) if isinstance(raw_input, dict) else None


class _PendingToolCall:
    """A tool call seen but not yet reported to on_tool_use.

    kimi-code's initial `tool_call` update usually has no `rawInput` — the
    input arrives on a later `tool_call_update` (ToolCallProgress). Holding
    the call until input shows up (or a boundary forces emission) keeps the
    work log from rendering empty tool entries.
    """

    __slots__ = ("tool_call_id", "title", "kind", "raw_input")

    def __init__(self, start):
        self.tool_call_id = start.tool_call_id
        self.title = start.title
        self.kind = start.kind
        self.raw_input = _raw_input(start)

    def merge_progress(self, progress) -> None:
        raw = getattr(progress, "raw", None)
        raw = raw if isinstance(raw, dict) else {}
        title = raw.get("title")
        if isinstance(title, str) and title:
            self.title = title
        new_input = _raw_input(progress)
        if new_input:
            self.raw_input = new_input

    @property
    def input(self) -> dict:
        input_dict = dict(self.raw_input or {})
        if self.kind:
            input_dict.setdefault("kind", self.kind)
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
        on_set_commit_message=None,
        on_clarify=None,
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
        self.on_set_commit_message = on_set_commit_message  # async callback(message: str) -> str
        self.on_clarify = on_clarify        # async callback(prompt: str, choices: list|None) -> str
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
        if self.on_set_commit_message:
            prompt += _COMMIT_MESSAGE_NOTE
        if self.on_clarify:
            prompt += _ASK_USER_NOTE
        self._task = asyncio.create_task(self._run(prompt, resume_session_id))

    async def _run(self, full_prompt: str, resume_session_id: str | None) -> None:
        try:
            try:
                from kimi_agent_sdk.acp import (
                    AcpClient,
                    AgentMessageChunk,
                    AgentThoughtChunk,
                    ToolCallProgress,
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

                # Select the model the way the ACP ecosystem does (see
                # flutter_kimi_sdk): session/set_config_option. The env var is
                # kept as a fallback for kimi-cli-era servers; kimi-code has
                # no ACP model flag. Best-effort — an unsupported option must
                # not kill the run (the CLI default model is used instead).
                if self.model:
                    try:
                        await client.connection.request(
                            "session/set_config_option",
                            {"sessionId": session.id, "configId": "model",
                             "value": self.model},
                        )
                    except Exception as e:
                        logger.warning(
                            f"Kimi mode: could not select model {self.model} via ACP "
                            f"({e}) — the CLI default model will be used"
                        )

                # ACP streams partial chunks; aggregate them so the work log
                # gets message-sized entries (like ClaudeAgentSession's blocks).
                text_buf: list[str] = []
                thought_buf: list[str] = []

                state = {"question": None}

                async def flush() -> None:
                    if thought_buf and self.on_thinking:
                        await self.on_thinking("".join(thought_buf))
                    thought_buf.clear()
                    text = "".join(text_buf)
                    text_buf.clear()
                    if self.on_set_commit_message:
                        text, commit_message = _extract_commit_message(text)
                        if commit_message:
                            await self.on_set_commit_message(commit_message)
                    if self.on_clarify:
                        text, question = _extract_ask_user(text)
                        if question:
                            state["question"] = question
                    if text.strip() and self.on_message:
                        await self.on_message(text)

                pending_tool: _PendingToolCall | None = None

                async def emit_pending() -> None:
                    nonlocal pending_tool
                    if pending_tool is not None and self.on_tool_use:
                        await self.on_tool_use(pending_tool.title, pending_tool.input)
                    pending_tool = None

                # Turn loop: normally one turn, but an ASK_USER line chains a
                # follow-up turn on the same (stateful) ACP session carrying
                # the user's answer.
                next_input = full_prompt
                while True:
                    state["question"] = None
                    stop_reason = None
                    async for item in session.prompt(next_input):
                        if self._cancelled:
                            return
                        if isinstance(item, AgentMessageChunk):
                            text_buf.append(_content_text(item.content))
                        elif isinstance(item, AgentThoughtChunk):
                            thought_buf.append(_content_text(item.content))
                        elif isinstance(item, ToolCallStart):
                            await flush()
                            await emit_pending()
                            pending_tool = _PendingToolCall(item)
                            if pending_tool.raw_input is not None:
                                await emit_pending()
                        elif isinstance(item, ToolCallProgress):
                            if (pending_tool is not None
                                    and pending_tool.tool_call_id == item.tool_call_id):
                                pending_tool.merge_progress(item)
                                if (pending_tool.raw_input is not None
                                        or item.status in ("completed", "failed")):
                                    await emit_pending()
                        elif isinstance(item, TurnEnded):
                            stop_reason = item.stop_reason
                    await emit_pending()
                    await flush()

                    if self._cancelled or stop_reason == "cancelled":
                        return
                    if stop_reason in _ABNORMAL_STOP_REASONS:
                        if self.on_error:
                            await self.on_error(f"Kimi run stopped early: {stop_reason}")
                        return
                    if state["question"] and self.on_clarify:
                        # Blocks until the user answers (Clarify column flow).
                        answer = await self.on_clarify(state["question"], None)
                        if self._cancelled:
                            return
                        next_input = f"User's answer: {answer}"
                        continue
                    break

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
