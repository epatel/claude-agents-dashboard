"""Agent-session callbacks for WorkflowService.

The ``_create_on_*_callback`` factories build the callbacks a session reports
back through (messages, tool use, thinking, completion, errors, clarifications,
permission requests), plus the completion bookkeeping they share. The board
tools' callbacks live in ``workflow_board_tools``.
A mixin: it relies on the services and state WorkflowService.__init__ sets up.
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from ..agent.session import AgentResult
from ..constants import AUTO_APPROVE_DIRECT, AUTO_APPROVE_REVIEW
from ..domain.item_state import Event
from .workflow_helpers import _worktree_of

# Logged under the WorkflowService module's name, as before the split.
logger = logging.getLogger(__name__.rsplit(".", 1)[0] + ".workflow_service")


class AgentCallbacksMixin:
    """Session-event callback factories and their helpers (see module docstring)."""

    # Callback creators
    def _create_on_message_callback(self, item_id: str):
        async def on_message(text: str):
            # Track the latest assistant message so the auto-review agent can
            # cite it as the implementing agent's "final message". Each new
            # text replaces the prior one — by the time on_complete fires the
            # last one wins, which is exactly what we want.
            if text:
                self._last_agent_message[item_id] = text
            await self._log_and_notify(item_id, "agent_message", text)
        return on_message

    def _create_on_tool_use_callback(self, item_id: str):
        async def on_tool_use(name: str, inp: Dict[str, Any]):
            formatted = self.notifications.format_tool_use(name, inp)
            # Tag Bash commands with yolo_command entry type when YOLO mode is active
            if name == "Bash" and item_id in self._yolo_items:
                entry_type = "yolo_command"
                formatted = f"⚡ {formatted}"
            else:
                entry_type = "tool_use"
            await self._log_and_notify(item_id, entry_type, formatted, json.dumps(inp))
        return on_tool_use

    def _create_on_thinking_callback(self, item_id: str):
        async def on_thinking(text: str):
            await self._log_and_notify(item_id, "thinking", text)
        return on_thinking

    def _create_on_complete_callback(self, item_id: str):
        async def on_complete(result: AgentResult):
            # Save token usage
            await self.db.save_token_usage(item_id, result)
            if result.success:
                await self._handle_agent_success(item_id, result)
            else:
                await self._handle_agent_failure(item_id, result)
            await self._release_session(item_id)

        return on_complete

    async def _handle_agent_success(self, item_id: str, result: AgentResult) -> None:
        """Log the cost, move the item to review, and kick off auto-approve if on."""
        # Create log message with cost and token info
        log_message = self.notifications.format_completion_log(
            result.cost_usd, result.total_tokens, result.input_tokens, result.output_tokens
        )
        await self._log_and_notify(item_id, "system", log_message)

        # Use commit message from session
        commit_message = self.sessions.get_commit_message(item_id)
        has_file_changes = await self._has_file_changes(item_id)

        extras: Dict[str, Any] = dict(
            session_id=result.session_id,
            has_file_changes=has_file_changes,
        )
        if commit_message:
            extras["commit_message"] = commit_message
        item = await self.items.transition(item_id, Event.COMPLETE, **extras)
        await self.notifications.broadcast_item_updated(item, source="agent")
        self._schedule_auto_approve(item_id, item, has_file_changes)

    async def _has_file_changes(self, item_id: str) -> int:
        """1 if the agent's worktree has changed files (or we can't tell), else 0."""
        current_item = await self.db.get_item(item_id)
        wt = _worktree_of(current_item)
        br = current_item.get("branch_name")
        if not (wt and br):
            return 1  # assume yes
        from ..git.operations import get_changed_files
        try:
            base = current_item.get("base_branch") or "main"
            base_commit = current_item.get("base_commit")
            changed = await get_changed_files(wt, br, base, wt, base_commit)
            return 1 if len(changed) > 0 else 0
        except Exception as e:
            logger.warning(f"Failed to check changed files for review: {e}")
            return 1

    def _schedule_auto_approve(self, item_id: str, item: Dict[str, Any], has_file_changes: int) -> None:
        """Auto-approve workflow. Tri-state (see constants.py):
          OFF    — leave it for a human in the Review column.
          REVIEW — spin up a read-only review agent (or, with no file changes,
                   approve directly since there's nothing to review).
          DIRECT — skip the review agent entirely and approve as soon as the
                   agent finishes.

        All paths are scheduled as background tasks so we don't block the
        completion callback (the review may take tens of seconds, and
        request_changes/approve_item create new sessions that would deadlock if
        awaited inline).
        """
        mode = int(item.get("auto_approve") or 0)
        if mode == AUTO_APPROVE_DIRECT:
            asyncio.create_task(self._auto_approve_direct(item_id))
        elif mode == AUTO_APPROVE_REVIEW:
            if has_file_changes:
                asyncio.create_task(self._run_auto_review(item_id))
            else:
                asyncio.create_task(self._auto_approve_no_changes(item_id))

    async def _handle_agent_failure(self, item_id: str, result: AgentResult) -> None:
        await self._log_and_notify(item_id, "error", f"Agent failed: {result.error}")
        item = await self.items.transition(
            item_id, Event.FAIL, session_id=result.session_id,
        )
        await self.notifications.broadcast_item_updated(item, source="agent")
        self._add_failure_notification(item_id, result.error, result.api_error_status)

    async def _release_session(self, item_id: str) -> None:
        """Bookkeeping once an agent session has ended (completed or errored)."""
        # Remove finished session from tracking so it no longer counts as active
        self.sessions.remove_session(item_id)
        await self._untrack_yolo(item_id)
        # Process queue — a slot just opened
        await self.process_queue()

    def _create_on_error_callback(self, item_id: str):
        async def on_error(error: str):
            await self._log_and_notify(item_id, "error", f"Agent error: {error}")
            item = await self.items.transition(item_id, Event.FAIL)
            await self.notifications.broadcast_item_updated(item, source="agent")
            self._add_failure_notification(item_id, error)
            await self._release_session(item_id)
        return on_error

    # HTTP statuses that indicate a transient, retryable API failure rather
    # than a real task error (rate limit, overload, gateway/server hiccups).
    _TRANSIENT_API_STATUSES = frozenset({429, 500, 502, 503, 529})

    def _add_failure_notification(self, item_id: str, error: str, api_error_status: int | None = None):
        """Add a system notification for agent failures.

        When the failure carries a transient API status (429/500/529, ...),
        classify it as retryable so the user knows it isn't their task at fault.
        """
        try:
            from ..web.routes import add_notification
            short_error = (error or "")[:200]
            if api_error_status in self._TRANSIENT_API_STATUSES:
                message = (
                    f"Agent {item_id[:8]} failed: API temporarily unavailable "
                    f"(HTTP {api_error_status}). This is transient — retry the item."
                )
            else:
                message = f"Agent {item_id[:8]} failed: {short_error}"
            add_notification("error", message, source=f"agent:{item_id[:8]}")
        except Exception:
            pass

    def _create_on_clarify_callback(self, item_id: str):
        async def on_clarify(prompt: str, choices: Optional[List[str]], context: Optional[str] = None) -> str:
            # Store clarification FIRST so that any client-side auto-transition
            # triggered by the upcoming item_updated broadcast (which fetches
            # /api/items/{id}/clarification) finds the row with context.
            # Otherwise the GET races the INSERT and the question dialog can
            # open without the context until the user closes and reopens it.
            await self.db.store_clarification(item_id, prompt, choices, context)

            # Move item to questions
            item = await self.items.transition(item_id, Event.ASK)
            await self.notifications.broadcast_item_updated(item, source="agent")
            log_message = f"Agent has a question: {prompt}"
            if context:
                log_message = f"{log_message}\n\n{context}"
            await self._log_and_notify(item_id, "system", log_message)

            # Broadcast to frontend (carries context directly so listeners that
            # don't auto-transition still get the panel populated immediately).
            await self.notifications.broadcast_clarification_requested(item_id, prompt, choices, context)

            # Wait for user response
            event = asyncio.Event()
            self._clarify_events[item_id] = event
            await event.wait()

            response = self._clarify_responses.pop(item_id, "")
            self._clarify_events.pop(item_id, None)

            # Move back to doing
            item = await self.items.transition(item_id, Event.ANSWER)
            await self.notifications.broadcast_item_updated(item)
            await self._log_and_notify(item_id, "system", f"User responded: {response}")

            return response

        return on_clarify

    # What differs between the agent's two permission requests (a bash command
    # vs. a built-in tool); the request/approve/deny flow itself is shared.
    _PERMISSION_KINDS: Dict[str, Dict[str, str]] = {
        "command": dict(
            prompt_tag="__permission_request__",
            request_verb="run",
            ws_event="permission_requested",
            ws_key="command",
            label="Command",
            save_method="save_allowed_command",
        ),
        "tool": dict(
            prompt_tag="__tool_request__",
            request_verb="use",
            ws_event="tool_permission_requested",
            ws_key="tool_name",
            label="Tool",
            save_method="save_allowed_builtin_tool",
        ),
    }

    def _create_on_request_command_callback(self, item_id: str):
        async def on_request_command(command: str, reason: str) -> str:
            return await self._request_permission(item_id, "command", command, reason)
        return on_request_command

    def _create_on_request_tool_callback(self, item_id: str):
        async def on_request_tool(tool_name: str, reason: str) -> str:
            return await self._request_permission(item_id, "tool", tool_name, reason)
        return on_request_tool

    async def _request_permission(self, item_id: str, kind: str, name: str, reason: str) -> str:
        """Ask the user to allow a command or tool; block until they answer.

        On approval the allow-list is updated and the session is restarted
        (from a separate task) so the new permission takes effect.
        """
        spec = self._PERMISSION_KINDS[kind]
        # Store as clarification FIRST so that any client-side auto-transition
        # triggered by the item_updated broadcast (which fetches
        # /api/items/{id}/clarification) finds the row immediately.
        await self.db.store_clarification(item_id, f"{spec['prompt_tag']}|{name}|{reason}", None)

        item = await self.items.transition(item_id, Event.ASK)
        await self.notifications.broadcast_item_updated(item, source="agent")
        await self._log_and_notify(
            item_id, "system",
            f"Agent requests permission to {spec['request_verb']} '{name}': {reason}"
        )
        await self.notifications.ws_manager.broadcast(
            spec["ws_event"],
            {"item_id": item_id, spec["ws_key"]: name, "reason": reason},
        )

        event = asyncio.Event()
        self._clarify_events[item_id] = event
        await event.wait()

        response = self._clarify_responses.pop(item_id, "denied")
        self._clarify_events.pop(item_id, None)

        if response == "approved":
            await getattr(self.db, spec["save_method"])(name)
            await self._log_and_notify(
                item_id, "system",
                f"{spec['label']} '{name}' approved — restarting session with updated permissions"
            )
            # Get session_id from the running session for resume
            old_session = self.sessions.sessions.get(item_id)
            resume_id = getattr(old_session, 'current_session_id', None) if old_session else None

            # Schedule restart as a separate task — we can't cleanup the
            # current session from inside it (we're running in its task).
            item = await self.db.get_item(item_id)
            asyncio.create_task(
                self._restart_session_with_new_permissions(item_id, name, resume_id, item)
            )
            # Return approved so the MCP tool handler exits cleanly.
            # The session will be killed and restarted by the task above.
            return "approved"

        await self._log_and_notify(item_id, "system", f"{spec['label']} '{name}' access denied")
        item = await self.items.transition(item_id, Event.ANSWER)
        await self.notifications.broadcast_item_updated(item)
        return response
