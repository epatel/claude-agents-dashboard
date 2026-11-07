"""Unit tests for WorkflowService."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from src.agent.session import AgentResult
from src.services.workflow_service import WorkflowService
from tests.unit.workflow_fixtures import (  # noqa: F401
    db, db_service, fetch_row, item, running_item, stage_item, tmp_dir,
    work_log_row, workflow,
)


# ---------------------------------------------------------------------------
# _log_and_notify
# ---------------------------------------------------------------------------

class TestLogAndNotify:
    async def test_logs_entry_and_broadcasts(self, workflow, item):
        await workflow._log_and_notify(item["id"], "system", "hello")
        # DB log entry should exist
        row = await work_log_row(workflow, item["id"], entry_type="system")
        assert row is not None
        assert row[0] == "hello"
        workflow.notifications.broadcast_agent_log.assert_awaited()

    async def test_logs_with_metadata(self, workflow, item):
        meta = json.dumps({"key": "val"})
        await workflow._log_and_notify(item["id"], "tool_use", "ran tool", meta)
        row = await work_log_row(workflow, item["id"], "metadata")
        assert row[0] == meta


# ---------------------------------------------------------------------------
# cancel_agent
# ---------------------------------------------------------------------------

class TestCancelAgent:
    async def test_cancel_moves_to_todo(self, workflow, db_service, item):
        # Put item in doing first
        await db_service.update_item(item["id"], column_name="doing", status="running")
        result = await workflow.cancel_agent(item["id"])
        assert result["column_name"] == "todo"
        assert result["status"] == "cancelled"

    async def test_cancel_cleans_up_session(self, workflow, item):
        await workflow.cancel_agent(item["id"])
        workflow.sessions.cleanup_session.assert_awaited_with(item["id"])

    async def test_cancel_broadcasts_yolo_mode_off_if_active(self, workflow, item):
        workflow._yolo_items.add(item["id"])
        await workflow.cancel_agent(item["id"])
        assert item["id"] not in workflow._yolo_items
        workflow.notifications.ws_manager.broadcast.assert_awaited()

    async def test_cancel_broadcasts_update(self, workflow, item):
        await workflow.cancel_agent(item["id"])
        workflow.notifications.broadcast_item_updated.assert_awaited()


# ---------------------------------------------------------------------------
# pause_agent
# ---------------------------------------------------------------------------

class TestPauseAgent:
    async def test_pause_sets_paused_status(self, workflow, running_item):
        result = await workflow.pause_agent(running_item["id"])
        assert result["status"] == "paused"

    async def test_pause_stores_session_id(self, workflow, running_item):
        result = await workflow.pause_agent(running_item["id"])
        assert result["session_id"] == "sess-paused-id"

    async def test_pause_broadcasts_update(self, workflow, running_item):
        await workflow.pause_agent(running_item["id"])
        workflow.notifications.broadcast_item_updated.assert_awaited()

    async def test_pause_no_session_id_still_pauses(self, workflow, running_item):
        workflow.sessions.pause_session = AsyncMock(return_value=None)
        result = await workflow.pause_agent(running_item["id"])
        assert result["status"] == "paused"

    async def test_pause_stores_message(self, workflow, running_item):
        result = await workflow.pause_agent(
            running_item["id"], message="investigate a simpler approach"
        )
        assert result["pause_message"] == "investigate a simpler approach"

    async def test_pause_strips_blank_message(self, workflow, running_item):
        # Pure whitespace shouldn't end up in the prompt as a phantom note.
        result = await workflow.pause_agent(running_item["id"], message="   \n  ")
        assert result["pause_message"] is None

    async def test_pause_no_message_leaves_field_unset(self, workflow, running_item):
        result = await workflow.pause_agent(running_item["id"])
        assert result.get("pause_message") in (None, "")


# ---------------------------------------------------------------------------
# resume_agent — pause-message handling
# ---------------------------------------------------------------------------

async def pause_with_worktree(workflow, item_id, **fields):
    """Put the item in the paused state with everything resume_agent
    expects to find on it."""
    await stage_item(
        workflow, item_id, "agent-test",
        column_name="doing", status="paused", session_id="sess-old", **fields,
    )
    return await workflow.db.get_item(item_id)


def resume_prompt(workflow):
    # start_session_task(item_id, session, prompt, attachments, resume_id)
    return workflow.sessions.start_session_task.await_args.args[2]


class TestResumeWithPauseMessage:
    @pytest_asyncio.fixture
    async def paused_item(self, workflow, item):
        return await pause_with_worktree(
            workflow, item["id"], pause_message="investigate a simpler approach"
        )

    async def test_resume_prepends_pause_message_to_prompt(
        self, workflow, paused_item
    ):
        await workflow.resume_agent(paused_item["id"])

        # start_session_task(item_id, session, prompt, attachments, resume_id)
        call = workflow.sessions.start_session_task.await_args
        assert call is not None
        prompt = call.args[2]
        assert "investigate a simpler approach" in prompt
        # The note must come BEFORE the standard "Continue working" preamble
        # so the agent sees the course-correction first.
        assert prompt.index("investigate a simpler approach") < prompt.index(
            "Continue working on your task"
        )

    async def test_resume_clears_pause_message(self, workflow, paused_item):
        await workflow.resume_agent(paused_item["id"])
        refreshed = await workflow.db.get_item(paused_item["id"])
        assert refreshed.get("pause_message") in (None, "")

    async def test_resume_without_pause_message_uses_plain_prompt(self, workflow, item):
        await pause_with_worktree(workflow, item["id"])
        await workflow.resume_agent(item["id"])
        prompt = resume_prompt(workflow)
        assert "paused you with this note" not in prompt

    async def test_resume_with_explicit_message_overrides_stored_note(
        self, workflow, paused_item
    ):
        # The new "Continue" form on the work-log dialog passes the user's
        # note via resume_agent(message=...). When supplied, it should win
        # over whatever pause_message happened to be on the item.
        await workflow.resume_agent(paused_item["id"], message="try plan B instead")
        prompt = resume_prompt(workflow)
        assert "try plan B instead" in prompt
        assert "investigate a simpler approach" not in prompt

    async def test_resume_with_blank_message_falls_back_to_stored_note(
        self, workflow, paused_item
    ):
        # Empty/whitespace-only submissions from the Continue form should
        # leave the stored pause_message in effect rather than wipe it out.
        await workflow.resume_agent(paused_item["id"], message="   \n  ")
        prompt = resume_prompt(workflow)
        assert "investigate a simpler approach" in prompt


# ---------------------------------------------------------------------------
# submit_clarification
# ---------------------------------------------------------------------------

class TestSubmitClarification:
    async def test_sets_clarify_response_and_signals_event(self, workflow, item):
        event = asyncio.Event()
        workflow._clarify_events[item["id"]] = event

        result = await workflow.submit_clarification(item["id"], "yes please")
        assert result == {"ok": True}
        assert event.is_set()
        assert workflow._clarify_responses[item["id"]] == "yes please"

    async def test_no_event_returns_ok(self, workflow, item):
        result = await workflow.submit_clarification(item["id"], "response")
        assert result == {"ok": True}

    async def test_updates_db_clarification_response(self, workflow, db_service, item):
        await db_service.store_clarification(item["id"], "What?", None)
        await workflow.submit_clarification(item["id"], "42")
        row = await fetch_row(
            workflow, "SELECT response FROM clarifications WHERE item_id = ?", item["id"]
        )
        assert row is not None
        assert row[0] == "42"


# ---------------------------------------------------------------------------
# delete_item
# ---------------------------------------------------------------------------

class TestDeleteItem:
    async def test_delete_returns_ok(self, workflow, item):
        result = await workflow.delete_item(item["id"])
        assert result == {"ok": True}

    async def test_delete_removes_from_db(self, workflow, db_service, item):
        await workflow.delete_item(item["id"])
        found = await db_service.get_item(item["id"])
        assert found is None

    async def test_delete_broadcasts_deletion(self, workflow, item):
        await workflow.delete_item(item["id"])
        workflow.notifications.broadcast_item_deleted.assert_awaited_with(item["id"])

    async def test_delete_cleans_up_git_resources(self, workflow, db_service, item):
        # Give item a worktree path
        await db_service.update_item(item["id"], worktree_path="/tmp/wt", branch_name="agent/test")
        await workflow.delete_item(item["id"])
        workflow.git.cleanup_item_resources.assert_awaited()

    async def test_delete_cleans_up_session(self, workflow, item):
        await workflow.delete_item(item["id"])
        workflow.sessions.cleanup_session.assert_awaited_with(item["id"])


# ---------------------------------------------------------------------------
# shutdown
# ---------------------------------------------------------------------------

class TestShutdown:
    async def test_shutdown_cleans_all_sessions(self, workflow):
        await workflow.shutdown()
        workflow.sessions.cleanup_all_sessions.assert_awaited_once()


# ---------------------------------------------------------------------------
# cancel_review
# ---------------------------------------------------------------------------

class TestCancelReview:
    async def test_cancel_review_moves_to_todo(self, workflow, db_service, item):
        await db_service.update_item(
            item["id"], column_name="review", worktree_path="/tmp/wt", branch_name="agent/x"
        )
        result = await workflow.cancel_review(item["id"])
        assert result["column_name"] == "todo"
        assert result["status"] is None
        assert result["worktree_path"] is None

    async def test_cancel_review_cleans_up_session(self, workflow, db_service, item):
        await db_service.update_item(item["id"], column_name="review")
        await workflow.cancel_review(item["id"])
        workflow.sessions.cleanup_session.assert_awaited_with(item["id"])

    async def test_cancel_review_cleans_up_git(self, workflow, db_service, item):
        await db_service.update_item(
            item["id"], column_name="review", worktree_path="/tmp/wt", branch_name="agent/x"
        )
        await workflow.cancel_review(item["id"])
        workflow.git.cleanup_item_resources.assert_awaited()

    async def test_cancel_review_raises_for_missing_item(self, workflow):
        with pytest.raises(ValueError, match="not found"):
            await workflow.cancel_review("does-not-exist")


# ---------------------------------------------------------------------------
# notify_and_auto_start_dependents
# ---------------------------------------------------------------------------

class TestNotifyAndAutoStartDependents:
    async def test_no_dependents_does_nothing(self, workflow, item):
        # Should not raise, no broadcast
        await workflow.notify_and_auto_start_dependents(item["id"])
        workflow.notifications.ws_manager.broadcast.assert_not_awaited()

    async def test_broadcasts_dependencies_resolved(self, workflow, db_service):
        parent = await db_service.create_todo_item("Parent", "p")
        child = await db_service.create_todo_item("Child", "c")
        await db_service.set_item_dependencies(child["id"], [parent["id"]])

        await workflow.notify_and_auto_start_dependents(parent["id"])
        workflow.notifications.ws_manager.broadcast.assert_awaited()
        call_args = workflow.notifications.ws_manager.broadcast.call_args_list
        event_types = [c[0][0] for c in call_args]
        assert "dependencies_resolved" in event_types

    async def test_auto_starts_unblocked_item(self, workflow, db_service, tmp_dir):
        parent = await db_service.create_todo_item("Parent", "p")
        child_data = await db_service.create_todo_item("Child", "c", auto_start=True)

        # Mark parent as done so child is unblocked
        await db_service.update_item(parent["id"], column_name="done")
        await db_service.set_item_dependencies(child_data["id"], [parent["id"]])

        # Setup start_agent mock on workflow
        workflow.sessions.create_session = AsyncMock(return_value=MagicMock())
        workflow.sessions.start_session_task = AsyncMock()
        workflow.git.create_or_reuse_worktree = AsyncMock(
            return_value=(tmp_dir / "wt", "agent/x", "main", "abc")
        )

        await workflow.notify_and_auto_start_dependents(parent["id"])
        # start_agent should have been called for the unblocked child
        workflow.sessions.create_session.assert_awaited()


class TestOnWhoAmICallback:
    async def test_returns_own_item_with_deps(self, workflow, db_service):
        parent = await db_service.create_todo_item("Parent", "p")
        me = await db_service.create_todo_item("Build foundation", "do it")
        await db_service.set_item_dependencies(me["id"], [parent["id"]])

        cb = workflow._create_on_who_am_i_callback(me["id"])
        result = await cb()

        assert result["id"] == me["id"]
        assert result["title"] == "Build foundation"
        assert result["column_name"] == "todo"
        assert [d["id"] for d in result["dependencies"]] == [parent["id"]]

    async def test_missing_item_returns_error(self, workflow):
        cb = workflow._create_on_who_am_i_callback("does-not-exist")
        result = await cb()
        assert "error" in result

    async def test_none_item_id_returns_error(self, workflow):
        cb = workflow._create_on_who_am_i_callback(None)
        result = await cb()
        assert "error" in result


# ---------------------------------------------------------------------------
# Callback: _create_on_message_callback
# ---------------------------------------------------------------------------

class TestOnMessageCallback:
    async def test_logs_agent_message(self, workflow, item):
        cb = workflow._create_on_message_callback(item["id"])
        await cb("Hello from agent")
        row = await work_log_row(workflow, item["id"], entry_type="agent_message")
        assert row is not None
        assert row[0] == "Hello from agent"


# ---------------------------------------------------------------------------
# Callback: _create_on_thinking_callback
# ---------------------------------------------------------------------------

class TestOnThinkingCallback:
    async def test_logs_thinking(self, workflow, item):
        cb = workflow._create_on_thinking_callback(item["id"])
        await cb("Thinking deeply...")
        row = await work_log_row(workflow, item["id"], entry_type="thinking")
        assert row is not None
        assert row[0] == "Thinking deeply..."


# ---------------------------------------------------------------------------
# Callback: _create_on_tool_use_callback
# ---------------------------------------------------------------------------

async def log_tool_use(workflow, item_id, tool, tool_input):
    """Run the tool-use callback; return the (entry_type, content) log row."""
    cb = workflow._create_on_tool_use_callback(item_id)
    await cb(tool, tool_input)
    return await work_log_row(workflow, item_id, "entry_type, content")


class TestOnToolUseCallback:
    async def test_logs_tool_use(self, workflow, item):
        row = await log_tool_use(workflow, item["id"], "ReadFile", {"path": "/tmp/foo.txt"})
        assert row is not None
        assert row[0] == "tool_use"

    async def test_yolo_bash_uses_yolo_entry_type(self, workflow, item):
        workflow._yolo_items.add(item["id"])
        row = await log_tool_use(workflow, item["id"], "Bash", {"command": "rm -rf /"})
        assert row[0] == "yolo_command"
        assert row[1].startswith("⚡")

    async def test_non_bash_in_yolo_mode_uses_tool_use(self, workflow, item):
        workflow._yolo_items.add(item["id"])
        row = await log_tool_use(workflow, item["id"], "ReadFile", {"path": "/tmp/x"})
        assert row[0] == "tool_use"


# ---------------------------------------------------------------------------
# Callback: _create_on_complete_callback
# ---------------------------------------------------------------------------

async def complete(workflow, item_id, **result):
    """Fire on_complete with ``AgentResult(**result)``; return the updated item."""
    result.setdefault("success", True)
    result.setdefault("session_id", "sess-abc")
    cb = workflow._create_on_complete_callback(item_id)
    await cb(AgentResult(**result))
    return await workflow.db.get_item(item_id)


class TestOnCompleteCallback:
    async def test_success_moves_to_review(self, workflow, running_item):
        updated = await complete(workflow, running_item["id"])
        assert updated["column_name"] == "review"

    async def test_failure_sets_failed_status(self, workflow, running_item):
        updated = await complete(workflow, running_item["id"], success=False,
                                 error="something went wrong", session_id="sess-fail")
        assert updated["status"] == "failed"

    async def test_success_stores_commit_message(self, workflow, running_item):
        workflow.sessions.get_commit_message = MagicMock(return_value="feat: my commit")
        updated = await complete(workflow, running_item["id"])
        assert updated["commit_message"] == "feat: my commit"

    async def test_removes_session_on_complete(self, workflow, running_item):
        await complete(workflow, running_item["id"])
        workflow.sessions.remove_session.assert_called_with(running_item["id"])

    async def test_clears_yolo_tracking_on_complete(self, workflow, running_item):
        workflow._yolo_items.add(running_item["id"])
        await complete(workflow, running_item["id"])
        assert running_item["id"] not in workflow._yolo_items

    async def test_broadcasts_item_updated_on_success(self, workflow, running_item):
        await complete(workflow, running_item["id"])
        workflow.notifications.broadcast_item_updated.assert_awaited()

    async def test_transient_api_failure_notification(self, workflow, running_item):
        with patch("src.web.routes.add_notification") as add_notif:
            await complete(workflow, running_item["id"], success=False,
                           error="[HTTP 529] Overloaded", session_id="sess-fail",
                           api_error_status=529)
        msg = add_notif.call_args[0][1]
        assert "HTTP 529" in msg
        assert "transient" in msg.lower()
        assert "retry" in msg.lower()


# ---------------------------------------------------------------------------
# _add_failure_notification — API error classification
# ---------------------------------------------------------------------------

def failure_message(workflow, error, status):
    """The notification text _add_failure_notification posts."""
    with patch("src.web.routes.add_notification") as add_notif:
        workflow._add_failure_notification("item1234", error, status)
    return add_notif.call_args[0][1]


class TestFailureNotification:
    @pytest.mark.parametrize("status", [429, 500, 502, 503, 529])
    def test_transient_status_marked_retryable(self, workflow, status):
        msg = failure_message(workflow, "boom", status)
        assert f"HTTP {status}" in msg
        assert "transient" in msg.lower()

    def test_non_transient_status_uses_raw_error(self, workflow):
        msg = failure_message(workflow, "real task error", 400)
        assert "real task error" in msg
        assert "transient" not in msg.lower()

    def test_no_status_uses_raw_error(self, workflow):
        msg = failure_message(workflow, "plain failure", None)
        assert "plain failure" in msg

    def test_error_is_truncated(self, workflow):
        msg = failure_message(workflow, "x" * 500, None)
        # 200-char cap on the error body (plus the fixed prefix).
        assert msg.count("x") == 200


# ---------------------------------------------------------------------------
# Callback: _create_on_error_callback
# ---------------------------------------------------------------------------

async def fail(workflow, item_id, error="error"):
    cb = workflow._create_on_error_callback(item_id)
    await cb(error)


class TestOnErrorCallback:
    async def test_sets_failed_status(self, workflow, running_item):
        await fail(workflow, running_item["id"], "some error")
        updated = await workflow.db.get_item(running_item["id"])
        assert updated["status"] == "failed"

    async def test_removes_session(self, workflow, running_item):
        await fail(workflow, running_item["id"])
        workflow.sessions.remove_session.assert_called_with(running_item["id"])

    async def test_broadcasts_item_updated(self, workflow, running_item):
        await fail(workflow, running_item["id"])
        workflow.notifications.broadcast_item_updated.assert_awaited()

    async def test_clears_yolo_on_error(self, workflow, running_item):
        workflow._yolo_items.add(running_item["id"])
        await fail(workflow, running_item["id"])
        assert running_item["id"] not in workflow._yolo_items


# ---------------------------------------------------------------------------
# Callback: _create_on_clarify_callback
# ---------------------------------------------------------------------------

async def ask(workflow, item_id, response, *call_args):
    """Run the clarify callback with ``response`` already answered.

    Pre-set the response and patch asyncio.Event with a set event so
    event.wait() returns immediately; return what the callback returns.
    """
    cb = workflow._create_on_clarify_callback(item_id)
    workflow._clarify_responses[item_id] = response
    pre_set_event = asyncio.Event()
    pre_set_event.set()
    with patch("asyncio.Event", return_value=pre_set_event):
        return await cb(*call_args)


def broadcast_context(workflow, *, required):
    """The ``context`` passed to broadcast_clarification_requested.

    Resolve regardless of positional vs keyword call style.
    """
    args, kwargs = workflow.notifications.broadcast_clarification_requested.call_args
    if "context" in kwargs:
        return kwargs["context"]
    if required:
        assert len(args) >= 4, f"expected context arg, got args={args}"
    return args[3] if len(args) >= 4 else None


async def clarification_row(workflow, item_id, columns):
    return await fetch_row(
        workflow, f"SELECT {columns} FROM clarifications WHERE item_id = ?", item_id
    )


class TestOnClarifyCallback:
    async def test_moves_item_to_questions(self, workflow, running_item):
        await ask(workflow, running_item["id"], "answer", "What color?", None)
        updated = await workflow.db.get_item(running_item["id"])
        assert updated["column_name"] == "doing"  # moved back after response

    async def test_returns_user_response(self, workflow, running_item):
        response = await ask(workflow, running_item["id"], "blue", "What color?", ["red", "blue"])
        assert response == "blue"

    async def test_broadcasts_clarification_requested(self, workflow, running_item):
        await ask(workflow, running_item["id"], "yes", "Continue?", ["yes", "no"])
        workflow.notifications.broadcast_clarification_requested.assert_awaited()

    async def test_persists_context_in_clarifications_table(self, workflow, running_item):
        await ask(workflow, running_item["id"], "ok",
                  "Approve plan?", ["yes", "no"], "Weighed options A and B; chose A.")
        row = await clarification_row(workflow, running_item["id"], "prompt, context")
        assert row is not None
        assert row[0] == "Approve plan?"
        assert row[1] == "Weighed options A and B; chose A."

    async def test_broadcast_payload_includes_context(self, workflow, running_item):
        await ask(workflow, running_item["id"], "ok",
                  "Approve plan?", ["yes", "no"], "Reasoning here.")
        workflow.notifications.broadcast_clarification_requested.assert_awaited()
        assert broadcast_context(workflow, required=True) == "Reasoning here."

    async def test_context_omitted_persists_null_and_broadcasts_none(
        self, workflow, running_item
    ):
        await ask(workflow, running_item["id"], "ok", "Question?", None)
        row = await clarification_row(workflow, running_item["id"], "context")
        assert row[0] is None
        assert broadcast_context(workflow, required=False) is None

    async def test_clarification_stored_before_item_updated_broadcast(
        self, workflow, db_service, running_item
    ):
        """Regression: question dialog opened on first auto-transition was
        missing context because store_clarification ran AFTER the item_updated
        broadcast, so a client GET racing the broadcast could miss the row.
        The callback must persist the clarification before broadcasting the
        column move so reopen-via-API always finds the latest context."""
        events: list[str] = []

        # Wrap store_clarification to record when it runs.
        real_store = db_service.store_clarification

        async def tracked_store(*args, **kwargs):
            events.append("store_clarification")
            return await real_store(*args, **kwargs)

        db_service.store_clarification = tracked_store

        async def tracked_broadcast_item_updated(*args, **kwargs):
            events.append("broadcast_item_updated")

        workflow.notifications.broadcast_item_updated.side_effect = (
            tracked_broadcast_item_updated
        )

        async def tracked_broadcast_clar(*args, **kwargs):
            events.append("broadcast_clarification_requested")

        workflow.notifications.broadcast_clarification_requested.side_effect = (
            tracked_broadcast_clar
        )

        await ask(workflow, running_item["id"], "ok", "Approve?", ["yes", "no"], "Reasoning here.")

        # Filter to the events we care about (broadcast_item_updated may be
        # called again for the move-back-to-doing transition).
        first_store_idx = events.index("store_clarification")
        first_broadcast_idx = events.index("broadcast_item_updated")
        assert first_store_idx < first_broadcast_idx, (
            f"store_clarification must run before broadcast_item_updated, "
            f"but events were: {events}"
        )


# ---------------------------------------------------------------------------
# Callback: _create_on_create_todo_callback
# ---------------------------------------------------------------------------

class TestOnCreateTodoCallback:
    async def test_creates_todo_item(self, workflow, item):
        cb = workflow._create_on_create_todo_callback(item["id"])
        new = await cb("Subtask", "desc of subtask")
        assert new["title"] == "Subtask"
        assert new["column_name"] == "todo"

    async def test_broadcasts_item_created(self, workflow, item):
        cb = workflow._create_on_create_todo_callback(item["id"])
        await cb("Subtask", "desc")
        workflow.notifications.broadcast_item_created.assert_awaited()

    async def test_sets_dependencies_when_requires_given(self, workflow, db_service, item):
        cb = workflow._create_on_create_todo_callback(item["id"])
        new = await cb("Dependent Task", "desc", requires=[item["id"]])
        deps = await db_service.get_item_dependencies(new["id"])
        assert item["id"] in [d["id"] for d in deps]

    async def test_autostart_without_requires_anchors_to_unmerged_creator(self, workflow, db_service, item):
        # The creating card (`item`) exists and hasn't merged, so an autostart
        # task with no requires must NOT start immediately — it auto-anchors a
        # dependency on the creator instead of branching off an unmerged main.
        workflow.sessions.create_session = AsyncMock(return_value=MagicMock())
        workflow.sessions.start_session_task = AsyncMock()
        cb = workflow._create_on_create_todo_callback(item["id"])
        new = await cb("Auto Task", "desc", autostart=True)
        assert not new.get("autostart_scheduled")
        deps = await db_service.get_item_dependencies(new["id"])
        assert [d["id"] for d in deps] == [item["id"]]

    async def test_autostart_with_requires_does_not_schedule(self, workflow, item):
        cb = workflow._create_on_create_todo_callback(item["id"])
        new = await cb("Blocked Task", "desc", requires=[item["id"]], autostart=True)
        assert not new.get("autostart_scheduled")

    async def test_use_chrome_persisted(self, workflow, item):
        cb = workflow._create_on_create_todo_callback(item["id"])
        new = await cb("Browse Task", "desc", use_chrome=True)
        assert new["use_chrome"] == 1

    async def test_use_chrome_defaults_off(self, workflow, item):
        cb = workflow._create_on_create_todo_callback(item["id"])
        new = await cb("Code Task", "desc")
        assert new["use_chrome"] == 0


# ---------------------------------------------------------------------------
# Callback: _create_on_create_epic_callback
# ---------------------------------------------------------------------------

class TestOnCreateEpicCallback:
    async def test_creates_epic(self, workflow, item):
        cb = workflow._create_on_create_epic_callback(item["id"])
        epic = await cb("My Epic", "#ff0000")
        assert epic["title"] == "My Epic"

    async def test_broadcasts_epic_created(self, workflow, item):
        cb = workflow._create_on_create_epic_callback(item["id"])
        await cb("Epic", "#123456")
        workflow.notifications.broadcast_epic_created.assert_awaited()

    async def test_returns_conventional_plan_path(self, workflow, item):
        cb = workflow._create_on_create_epic_callback(item["id"])
        epic = await cb("Realtime Canvas", "blue")
        # Same convention the prompt injection uses, so they always agree.
        assert epic["plan_path"] == "plans/realtime-canvas.md"


class TestEpicSessionPlan:
    async def test_item_session_kwargs_sets_epic_plan_relpath(self, workflow, db_service):
        epic = await workflow.epics.create("Realtime Canvas", "blue")
        item = await db_service.create_todo_item("Task", "desc", epic_id=epic["id"])
        kwargs = await workflow._item_session_kwargs(item)
        assert kwargs["epic_plan_relpath"] == "plans/realtime-canvas.md"

    async def test_item_session_kwargs_no_epic_no_plan(self, workflow, db_service):
        item = await db_service.create_todo_item("Task", "desc")
        kwargs = await workflow._item_session_kwargs(item)
        assert "epic_plan_relpath" not in kwargs


# ---------------------------------------------------------------------------
# Callback: _create_on_delete_todo_callback
# ---------------------------------------------------------------------------

class TestOnDeleteTodoCallback:
    async def test_deletes_todo_item(self, workflow, db_service, item):
        cb = workflow._create_on_delete_todo_callback(item["id"])
        result = await cb(item["id"])
        assert "Deleted" in result
        found = await db_service.get_item(item["id"])
        assert found is None

    async def test_cannot_delete_non_todo_item(self, workflow, db_service, item):
        await db_service.update_item(item["id"], column_name="doing")
        cb = workflow._create_on_delete_todo_callback(item["id"])
        result = await cb(item["id"])
        assert "Cannot delete" in result

    async def test_returns_not_found_for_missing_item(self, workflow, item):
        cb = workflow._create_on_delete_todo_callback(item["id"])
        result = await cb("nonexistent-id")
        assert "not found" in result

    async def test_broadcasts_item_deleted(self, workflow, item):
        cb = workflow._create_on_delete_todo_callback(item["id"])
        await cb(item["id"])
        workflow.notifications.broadcast_item_deleted.assert_awaited_with(item["id"])


# ---------------------------------------------------------------------------
# Callback: _create_on_set_commit_message_callback
# ---------------------------------------------------------------------------

class TestOnSetCommitMessageCallback:
    async def test_calls_sessions_set_commit_message(self, workflow, item):
        cb = workflow._create_on_set_commit_message_callback(item["id"])
        result = await cb("feat: add feature")
        workflow.sessions.set_commit_message.assert_called_with(item["id"], "feat: add feature")
        assert result == "ok"

    async def test_logs_commit_message(self, workflow, item):
        cb = workflow._create_on_set_commit_message_callback(item["id"])
        await cb("feat: add feature")
        row = await work_log_row(workflow, item["id"], entry_type="system")
        assert row is not None
        assert "feat: add feature" in row[0]


# ---------------------------------------------------------------------------
# Callback: _create_on_create_shortcut_callback
# ---------------------------------------------------------------------------

class TestOnCreateShortcutCallback:
    async def test_creates_shortcut_file(self, workflow, item, tmp_dir):
        cb = workflow._create_on_create_shortcut_callback(item["id"])
        result = await cb("build", "npm run build")
        assert result["name"] == "build"
        assert result["command"] == "npm run build"
        shortcuts_path = tmp_dir / "shortcuts.json"
        assert shortcuts_path.exists()
        shortcuts = json.loads(shortcuts_path.read_text())
        assert any(s["name"] == "build" for s in shortcuts)

    async def test_no_data_dir_returns_error(self, workflow, item):
        workflow.data_dir = None
        cb = workflow._create_on_create_shortcut_callback(item["id"])
        result = await cb("build", "npm run build")
        assert "error" in result

    async def test_appends_to_existing_shortcuts(self, workflow, item, tmp_dir):
        shortcuts_path = tmp_dir / "shortcuts.json"
        shortcuts_path.write_text(json.dumps([{"id": "abc", "name": "existing", "command": "echo hi"}]))
        cb = workflow._create_on_create_shortcut_callback(item["id"])
        await cb("new", "npm test")
        shortcuts = json.loads(shortcuts_path.read_text())
        assert len(shortcuts) == 2


# ---------------------------------------------------------------------------
# Callback: _create_on_view_board_callback
# ---------------------------------------------------------------------------

class TestOnViewBoardCallback:
    async def test_returns_string_with_items(self, workflow, db_service, item):
        cb = workflow._create_on_view_board_callback()
        result = await cb()
        assert isinstance(result, str)
        assert item["title"] in result

    async def test_empty_board_returns_no_items_indicator(self, workflow):
        cb = workflow._create_on_view_board_callback()
        result = await cb()
        assert isinstance(result, str)
        assert len(result) > 0  # Should return some board representation even when empty


# ---------------------------------------------------------------------------
# cleanup_stale_worktree
# ---------------------------------------------------------------------------

class TestCleanupStaleWorktree:
    async def test_clears_git_metadata_on_item(self, workflow, db_service, item):
        await db_service.update_item(
            item["id"],
            worktree_path="/tmp/wt",
            branch_name="agent/test",
            base_branch="main",
        )
        result = await workflow.cleanup_stale_worktree(item["id"])
        assert result["ok"] is True
        updated = await db_service.get_item(item["id"])
        assert updated["worktree_path"] is None
        assert updated["branch_name"] is None

    async def test_calls_git_cleanup(self, workflow, item):
        await workflow.cleanup_stale_worktree(item["id"])
        workflow.git.cleanup_item_resources.assert_awaited()

    async def test_works_when_item_not_in_db(self, workflow):
        result = await workflow.cleanup_stale_worktree("no-such-id")
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# start_copy_agent
# ---------------------------------------------------------------------------

class TestStartCopyAgent:
    async def test_raises_if_item_not_in_todo(self, workflow, db_service, item):
        await db_service.update_item(item["id"], column_name="doing")
        with pytest.raises(ValueError, match="todo"):
            await workflow.start_copy_agent(item["id"])

    async def test_raises_for_missing_item(self, workflow):
        with pytest.raises(ValueError, match="not found"):
            await workflow.start_copy_agent("missing-id")

    async def test_broadcasts_item_created_for_copy(self, workflow, db_service, item, tmp_dir):
        wt = tmp_dir / "worktrees" / "agent-copy"
        wt.mkdir(parents=True, exist_ok=True)
        workflow.git.create_or_reuse_worktree = AsyncMock(
            return_value=(wt, "agent/copy", "main", "abc")
        )
        await workflow.start_copy_agent(item["id"])
        workflow.notifications.broadcast_item_created.assert_awaited()


# ---------------------------------------------------------------------------
# retry_agent
# ---------------------------------------------------------------------------

class TestRetryAgent:
    async def test_raises_for_missing_item(self, workflow):
        with pytest.raises(ValueError, match="not found"):
            await workflow.retry_agent("missing-id")

    async def test_sets_running_status(self, workflow, db_service, item, tmp_dir):
        wt = tmp_dir / "worktrees" / "agent-test"
        wt.mkdir(parents=True, exist_ok=True)
        await db_service.update_item(
            item["id"], column_name="doing", status="failed",
            worktree_path=str(wt), branch_name="agent/test"
        )
        workflow.git.create_or_reuse_worktree = AsyncMock(
            return_value=(wt, "agent/test", "main", "abc")
        )
        result = await workflow.retry_agent(item["id"])
        assert result["status"] == "running"
        assert result["column_name"] == "doing"


class TestCreateAgentTodo:
    @pytest.mark.asyncio
    async def test_delegates_to_create_todo_callback(self):
        """create_agent_todo runs the exact same callback the MCP tool uses."""
        svc = MagicMock()
        inner = AsyncMock(return_value={"id": "new1", "title": "T"})
        svc._create_on_create_todo_callback = MagicMock(return_value=inner)

        result = await WorkflowService.create_agent_todo(
            svc, "creator-1", title="T", description="d",
            requires=["dep1"], autostart=True, auto_approve=2, use_chrome=True,
        )

        svc._create_on_create_todo_callback.assert_called_once_with("creator-1")
        inner.assert_awaited_once_with(
            "T", "d", epic_id=None, requires=["dep1"],
            autostart=True, auto_approve=2, use_chrome=True,
        )
        assert result == {"id": "new1", "title": "T"}
