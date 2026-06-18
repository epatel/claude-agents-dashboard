"""Unit tests for WorkflowService."""

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from src.database import Database
from src.agent.session import AgentResult
from src.services.database_service import DatabaseService
from src.services.git_service import GitService
from src.services.notification_service import NotificationService
from src.services.session_service import SessionService
from src.services.workflow_service import WorkflowService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest_asyncio.fixture
async def db(tmp_dir):
    db_path = tmp_dir / "test.db"
    database = Database(db_path)
    await database.initialize()
    yield database


@pytest_asyncio.fixture
async def db_service(db):
    return DatabaseService(db)


@pytest_asyncio.fixture
async def workflow(db_service, tmp_dir):
    git_service = MagicMock(spec=GitService)
    git_service.target_project = tmp_dir
    git_service.worktree_dir = tmp_dir / "worktrees"
    git_service.worktree_dir.mkdir(exist_ok=True)
    git_service.create_or_reuse_worktree = AsyncMock(
        return_value=(tmp_dir / "worktrees" / "agent-test", "agent/test", "main", "abc123")
    )
    git_service.cleanup_session = AsyncMock()
    git_service.cleanup_item_resources = AsyncMock()
    git_service.cleanup_worktree_and_branch = AsyncMock()

    ws_manager = MagicMock()
    ws_manager.broadcast = AsyncMock()
    notif_service = NotificationService(ws_manager)
    notif_service.broadcast_item_updated = AsyncMock()
    notif_service.broadcast_item_created = AsyncMock()
    notif_service.broadcast_item_deleted = AsyncMock()
    notif_service.broadcast_agent_log = AsyncMock()
    notif_service.broadcast_clarification_requested = AsyncMock()
    notif_service.broadcast_epic_created = AsyncMock()

    session_service = MagicMock(spec=SessionService)
    session_service.sessions = {}
    session_service.cleanup_session = AsyncMock()
    session_service.cleanup_all_sessions = AsyncMock()
    session_service.pause_session = AsyncMock(return_value="sess-paused-id")
    session_service.create_session = AsyncMock(return_value=MagicMock())
    session_service.start_session_task = AsyncMock()
    session_service.get_commit_message = MagicMock(return_value=None)
    session_service.set_commit_message = MagicMock(return_value="ok")
    session_service.remove_session = MagicMock()

    wf = WorkflowService(db_service, git_service, notif_service, session_service, tmp_dir)
    yield wf


@pytest_asyncio.fixture
async def item(db_service):
    """A base todo item."""
    return await db_service.create_todo_item("Test Task", "Do something useful")


# ---------------------------------------------------------------------------
# _log_and_notify
# ---------------------------------------------------------------------------

class TestLogAndNotify:
    async def test_logs_entry_and_broadcasts(self, workflow, item):
        await workflow._log_and_notify(item["id"], "system", "hello")
        # DB log entry should exist
        async with workflow.db.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT content FROM work_log WHERE item_id = ? AND entry_type = 'system'",
                (item["id"],),
            )
            row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "hello"
        workflow.notifications.broadcast_agent_log.assert_awaited()

    async def test_logs_with_metadata(self, workflow, item):
        meta = json.dumps({"key": "val"})
        await workflow._log_and_notify(item["id"], "tool_use", "ran tool", meta)
        async with workflow.db.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT metadata FROM work_log WHERE item_id = ?", (item["id"],)
            )
            row = await cursor.fetchone()
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
    @pytest_asyncio.fixture
    async def running_item(self, db_service, item):
        # Pause is only valid from RUNNING; production never exposes a Pause
        # button on a backlog item. Move the item there before each test.
        await db_service.update_item(item["id"], column_name="doing", status="running")
        return item

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

class TestResumeWithPauseMessage:
    @pytest_asyncio.fixture
    async def paused_item(self, db_service, tmp_dir, item):
        # Set up an item in the paused state with everything resume_agent
        # expects to find on it.
        worktree = tmp_dir / "worktrees" / "agent-test"
        worktree.mkdir(parents=True, exist_ok=True)
        await db_service.update_item(
            item["id"],
            column_name="doing",
            status="paused",
            worktree_path=str(worktree),
            session_id="sess-old",
            pause_message="investigate a simpler approach",
        )
        return await db_service.get_item(item["id"])

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

    async def test_resume_without_pause_message_uses_plain_prompt(
        self, workflow, db_service, tmp_dir, item
    ):
        worktree = tmp_dir / "worktrees" / "agent-test"
        worktree.mkdir(parents=True, exist_ok=True)
        await db_service.update_item(
            item["id"],
            column_name="doing",
            status="paused",
            worktree_path=str(worktree),
            session_id="sess-old",
        )
        await workflow.resume_agent(item["id"])
        prompt = workflow.sessions.start_session_task.await_args.args[2]
        assert "paused you with this note" not in prompt

    async def test_resume_with_explicit_message_overrides_stored_note(
        self, workflow, paused_item
    ):
        # The new "Continue" form on the work-log dialog passes the user's
        # note via resume_agent(message=...). When supplied, it should win
        # over whatever pause_message happened to be on the item.
        await workflow.resume_agent(paused_item["id"], message="try plan B instead")
        prompt = workflow.sessions.start_session_task.await_args.args[2]
        assert "try plan B instead" in prompt
        assert "investigate a simpler approach" not in prompt

    async def test_resume_with_blank_message_falls_back_to_stored_note(
        self, workflow, paused_item
    ):
        # Empty/whitespace-only submissions from the Continue form should
        # leave the stored pause_message in effect rather than wipe it out.
        await workflow.resume_agent(paused_item["id"], message="   \n  ")
        prompt = workflow.sessions.start_session_task.await_args.args[2]
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
        async with workflow.db.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT response FROM clarifications WHERE item_id = ?", (item["id"],)
            )
            row = await cursor.fetchone()
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
        async with workflow.db.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT content FROM work_log WHERE item_id = ? AND entry_type = 'agent_message'",
                (item["id"],),
            )
            row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "Hello from agent"


# ---------------------------------------------------------------------------
# Callback: _create_on_thinking_callback
# ---------------------------------------------------------------------------

class TestOnThinkingCallback:
    async def test_logs_thinking(self, workflow, item):
        cb = workflow._create_on_thinking_callback(item["id"])
        await cb("Thinking deeply...")
        async with workflow.db.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT content FROM work_log WHERE item_id = ? AND entry_type = 'thinking'",
                (item["id"],),
            )
            row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "Thinking deeply..."


# ---------------------------------------------------------------------------
# Callback: _create_on_tool_use_callback
# ---------------------------------------------------------------------------

class TestOnToolUseCallback:
    async def test_logs_tool_use(self, workflow, item):
        cb = workflow._create_on_tool_use_callback(item["id"])
        await cb("ReadFile", {"path": "/tmp/foo.txt"})
        async with workflow.db.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT entry_type FROM work_log WHERE item_id = ?", (item["id"],)
            )
            row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "tool_use"

    async def test_yolo_bash_uses_yolo_entry_type(self, workflow, item):
        workflow._yolo_items.add(item["id"])
        cb = workflow._create_on_tool_use_callback(item["id"])
        await cb("Bash", {"command": "rm -rf /"})
        async with workflow.db.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT entry_type, content FROM work_log WHERE item_id = ?", (item["id"],)
            )
            row = await cursor.fetchone()
        assert row[0] == "yolo_command"
        assert row[1].startswith("⚡")

    async def test_non_bash_in_yolo_mode_uses_tool_use(self, workflow, item):
        workflow._yolo_items.add(item["id"])
        cb = workflow._create_on_tool_use_callback(item["id"])
        await cb("ReadFile", {"path": "/tmp/x"})
        async with workflow.db.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT entry_type FROM work_log WHERE item_id = ?", (item["id"],)
            )
            row = await cursor.fetchone()
        assert row[0] == "tool_use"


# ---------------------------------------------------------------------------
# Callback: _create_on_complete_callback
# ---------------------------------------------------------------------------

class TestOnCompleteCallback:
    @pytest_asyncio.fixture
    async def running_item(self, db_service, item):
        # on_complete fires when an active agent's session ends — i.e. while
        # the item is RUNNING (or RESOLVING_CONFLICTS). Mirror production.
        await db_service.update_item(item["id"], column_name="doing", status="running")
        return item

    async def test_success_moves_to_review(self, workflow, running_item):
        result = AgentResult(success=True, session_id="sess-abc")
        cb = workflow._create_on_complete_callback(running_item["id"])
        await cb(result)
        updated = await workflow.db.get_item(running_item["id"])
        assert updated["column_name"] == "review"

    async def test_failure_sets_failed_status(self, workflow, running_item):
        result = AgentResult(success=False, error="something went wrong", session_id="sess-fail")
        cb = workflow._create_on_complete_callback(running_item["id"])
        await cb(result)
        updated = await workflow.db.get_item(running_item["id"])
        assert updated["status"] == "failed"

    async def test_success_stores_commit_message(self, workflow, running_item):
        workflow.sessions.get_commit_message = MagicMock(return_value="feat: my commit")
        result = AgentResult(success=True, session_id="sess-abc")
        cb = workflow._create_on_complete_callback(running_item["id"])
        await cb(result)
        updated = await workflow.db.get_item(running_item["id"])
        assert updated["commit_message"] == "feat: my commit"

    async def test_removes_session_on_complete(self, workflow, running_item):
        result = AgentResult(success=True, session_id="sess-abc")
        cb = workflow._create_on_complete_callback(running_item["id"])
        await cb(result)
        workflow.sessions.remove_session.assert_called_with(running_item["id"])

    async def test_clears_yolo_tracking_on_complete(self, workflow, running_item):
        workflow._yolo_items.add(running_item["id"])
        result = AgentResult(success=True, session_id="sess-abc")
        cb = workflow._create_on_complete_callback(running_item["id"])
        await cb(result)
        assert running_item["id"] not in workflow._yolo_items

    async def test_broadcasts_item_updated_on_success(self, workflow, running_item):
        result = AgentResult(success=True, session_id="sess-abc")
        cb = workflow._create_on_complete_callback(running_item["id"])
        await cb(result)
        workflow.notifications.broadcast_item_updated.assert_awaited()

    async def test_transient_api_failure_notification(self, workflow, running_item):
        result = AgentResult(success=False, error="[HTTP 529] Overloaded",
                             session_id="sess-fail", api_error_status=529)
        cb = workflow._create_on_complete_callback(running_item["id"])
        with patch("src.web.routes.add_notification") as add_notif:
            await cb(result)
        msg = add_notif.call_args[0][1]
        assert "HTTP 529" in msg
        assert "transient" in msg.lower()
        assert "retry" in msg.lower()


# ---------------------------------------------------------------------------
# _add_failure_notification — API error classification
# ---------------------------------------------------------------------------

class TestFailureNotification:
    @pytest.mark.parametrize("status", [429, 500, 502, 503, 529])
    def test_transient_status_marked_retryable(self, workflow, status):
        with patch("src.web.routes.add_notification") as add_notif:
            workflow._add_failure_notification("item1234", "boom", status)
        msg = add_notif.call_args[0][1]
        assert f"HTTP {status}" in msg
        assert "transient" in msg.lower()

    def test_non_transient_status_uses_raw_error(self, workflow):
        with patch("src.web.routes.add_notification") as add_notif:
            workflow._add_failure_notification("item1234", "real task error", 400)
        msg = add_notif.call_args[0][1]
        assert "real task error" in msg
        assert "transient" not in msg.lower()

    def test_no_status_uses_raw_error(self, workflow):
        with patch("src.web.routes.add_notification") as add_notif:
            workflow._add_failure_notification("item1234", "plain failure", None)
        msg = add_notif.call_args[0][1]
        assert "plain failure" in msg

    def test_error_is_truncated(self, workflow):
        with patch("src.web.routes.add_notification") as add_notif:
            workflow._add_failure_notification("item1234", "x" * 500, None)
        msg = add_notif.call_args[0][1]
        # 200-char cap on the error body (plus the fixed prefix).
        assert msg.count("x") == 200


# ---------------------------------------------------------------------------
# Callback: _create_on_error_callback
# ---------------------------------------------------------------------------

class TestOnErrorCallback:
    @pytest_asyncio.fixture
    async def running_item(self, db_service, item):
        # on_error fires from an active agent — same RUNNING-state setup
        # as on_complete; FAIL is only valid from RUNNING/RESOLVING_CONFLICTS.
        await db_service.update_item(item["id"], column_name="doing", status="running")
        return item

    async def test_sets_failed_status(self, workflow, running_item):
        cb = workflow._create_on_error_callback(running_item["id"])
        await cb("some error")
        updated = await workflow.db.get_item(running_item["id"])
        assert updated["status"] == "failed"

    async def test_removes_session(self, workflow, running_item):
        cb = workflow._create_on_error_callback(running_item["id"])
        await cb("error")
        workflow.sessions.remove_session.assert_called_with(running_item["id"])

    async def test_broadcasts_item_updated(self, workflow, running_item):
        cb = workflow._create_on_error_callback(running_item["id"])
        await cb("error")
        workflow.notifications.broadcast_item_updated.assert_awaited()

    async def test_clears_yolo_on_error(self, workflow, running_item):
        workflow._yolo_items.add(running_item["id"])
        cb = workflow._create_on_error_callback(running_item["id"])
        await cb("error")
        assert running_item["id"] not in workflow._yolo_items


# ---------------------------------------------------------------------------
# Callback: _create_on_clarify_callback
# ---------------------------------------------------------------------------

class TestOnClarifyCallback:
    @pytest_asyncio.fixture
    async def running_item(self, db_service, item):
        # on_clarify is only invoked by an active agent — i.e. on a RUNNING item.
        # Move the freshly-created todo item into the RUNNING state so the
        # ASK transition (RUNNING -> CLARIFY) is valid.
        await db_service.update_item(item["id"], column_name="doing", status="running")
        return item

    async def test_moves_item_to_questions(self, workflow, running_item):
        cb = workflow._create_on_clarify_callback(running_item["id"])

        # Pre-set the response so event.wait() returns immediately
        workflow._clarify_responses[running_item["id"]] = "answer"
        pre_set_event = asyncio.Event()
        pre_set_event.set()

        def make_pre_set_event():
            return pre_set_event
        with patch("asyncio.Event", side_effect=make_pre_set_event):
            await cb("What color?", None)
        updated = await workflow.db.get_item(running_item["id"])
        assert updated["column_name"] == "doing"  # moved back after response

    async def test_returns_user_response(self, workflow, running_item):
        cb = workflow._create_on_clarify_callback(running_item["id"])

        workflow._clarify_responses[running_item["id"]] = "blue"
        pre_set_event = asyncio.Event()
        pre_set_event.set()
        with patch("asyncio.Event", return_value=pre_set_event):
            response = await cb("What color?", ["red", "blue"])
        assert response == "blue"

    async def test_broadcasts_clarification_requested(self, workflow, running_item):
        cb = workflow._create_on_clarify_callback(running_item["id"])

        workflow._clarify_responses[running_item["id"]] = "yes"
        pre_set_event = asyncio.Event()
        pre_set_event.set()
        with patch("asyncio.Event", return_value=pre_set_event):
            await cb("Continue?", ["yes", "no"])
        workflow.notifications.broadcast_clarification_requested.assert_awaited()

    async def test_persists_context_in_clarifications_table(self, workflow, db_service, running_item):
        cb = workflow._create_on_clarify_callback(running_item["id"])

        workflow._clarify_responses[running_item["id"]] = "ok"
        pre_set_event = asyncio.Event()
        pre_set_event.set()
        with patch("asyncio.Event", return_value=pre_set_event):
            await cb(
                "Approve plan?",
                ["yes", "no"],
                "Weighed options A and B; chose A.",
            )

        async with db_service.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT prompt, context FROM clarifications WHERE item_id = ?",
                (running_item["id"],),
            )
            row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "Approve plan?"
        assert row[1] == "Weighed options A and B; chose A."

    async def test_broadcast_payload_includes_context(self, workflow, running_item):
        cb = workflow._create_on_clarify_callback(running_item["id"])

        workflow._clarify_responses[running_item["id"]] = "ok"
        pre_set_event = asyncio.Event()
        pre_set_event.set()
        with patch("asyncio.Event", return_value=pre_set_event):
            await cb("Approve plan?", ["yes", "no"], "Reasoning here.")

        broadcast = workflow.notifications.broadcast_clarification_requested
        broadcast.assert_awaited()
        args, kwargs = broadcast.call_args
        # Resolve regardless of positional vs keyword call style.
        if "context" in kwargs:
            ctx_value = kwargs["context"]
        else:
            assert len(args) >= 4, f"expected context arg, got args={args}"
            ctx_value = args[3]
        assert ctx_value == "Reasoning here."

    async def test_context_omitted_persists_null_and_broadcasts_none(
        self, workflow, db_service, running_item
    ):
        cb = workflow._create_on_clarify_callback(running_item["id"])

        workflow._clarify_responses[running_item["id"]] = "ok"
        pre_set_event = asyncio.Event()
        pre_set_event.set()
        with patch("asyncio.Event", return_value=pre_set_event):
            await cb("Question?", None)

        async with db_service.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT context FROM clarifications WHERE item_id = ?",
                (running_item["id"],),
            )
            row = await cursor.fetchone()
        assert row[0] is None

        broadcast = workflow.notifications.broadcast_clarification_requested
        args, kwargs = broadcast.call_args
        if "context" in kwargs:
            ctx_value = kwargs["context"]
        elif len(args) >= 4:
            ctx_value = args[3]
        else:
            ctx_value = None
        assert ctx_value is None

    async def test_clarification_stored_before_item_updated_broadcast(
        self, workflow, db_service, running_item
    ):
        """Regression: question dialog opened on first auto-transition was
        missing context because store_clarification ran AFTER the item_updated
        broadcast, so a client GET racing the broadcast could miss the row.
        The callback must persist the clarification before broadcasting the
        column move so reopen-via-API always finds the latest context."""
        cb = workflow._create_on_clarify_callback(running_item["id"])

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

        workflow._clarify_responses[running_item["id"]] = "ok"
        pre_set_event = asyncio.Event()
        pre_set_event.set()
        with patch("asyncio.Event", return_value=pre_set_event):
            await cb("Approve?", ["yes", "no"], "Reasoning here.")

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

    async def test_autostart_without_requires_schedules_task(self, workflow, item):
        workflow.sessions.create_session = AsyncMock(return_value=MagicMock())
        workflow.sessions.start_session_task = AsyncMock()
        cb = workflow._create_on_create_todo_callback(item["id"])
        new = await cb("Auto Task", "desc", autostart=True)
        assert new.get("autostart_scheduled") is True

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
        async with workflow.db.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT content FROM work_log WHERE item_id = ? AND entry_type = 'system'",
                (item["id"],),
            )
            row = await cursor.fetchone()
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


# ---------------------------------------------------------------------------
# Auto-approve: items without file changes
# ---------------------------------------------------------------------------

class TestAutoApproveNoChanges:
    """Auto-approve must also handle items where the agent finished without
    producing any file changes — i.e. the review card shows a "Done" button
    instead of "Approve & Merge". Without this path the card just sits in
    review forever."""

    @pytest_asyncio.fixture
    async def review_item(self, db_service, item, tmp_dir):
        # Item that's landed in review with auto_approve set and a worktree
        # path. No diff (no commits, no modified files) — this is what
        # has_file_changes=0 looks like in practice.
        wt = tmp_dir / "worktrees" / "no-changes"
        wt.mkdir(parents=True, exist_ok=True)
        await db_service.update_item(
            item["id"],
            column_name="review",
            status=None,
            auto_approve=1,
            has_file_changes=0,
            worktree_path=str(wt),
            branch_name="agent/no-changes",
            base_branch="main",
        )
        return item

    async def test_no_changes_path_moves_item_to_done(
        self, workflow, review_item
    ):
        # approve_item internally calls run_git("status") and get_changed_files;
        # patch both to simulate a clean repo with zero agent-touched files.
        with patch("src.git.operations.run_git", new=AsyncMock(return_value="")), \
             patch("src.git.operations.get_changed_files",
                   new=AsyncMock(return_value=[])):
            await workflow._auto_approve_no_changes(review_item["id"])
        updated = await workflow.db.get_item(review_item["id"])
        assert updated["column_name"] == "done"

    async def test_no_changes_path_skips_merge_call(
        self, workflow, review_item
    ):
        workflow.git.merge_agent_work = AsyncMock(return_value=(True, "ok"))
        with patch("src.git.operations.run_git", new=AsyncMock(return_value="")), \
             patch("src.git.operations.get_changed_files",
                   new=AsyncMock(return_value=[])):
            await workflow._auto_approve_no_changes(review_item["id"])
        # No diff → no merge.
        workflow.git.merge_agent_work.assert_not_called()

    async def test_no_changes_path_broadcasts_item_updated(
        self, workflow, review_item
    ):
        # Regression: the no-changes branch in approve_item used to skip
        # broadcast_item_updated, so the frontend never saw the column change
        # and the card stayed in Review until a reload.
        with patch("src.git.operations.run_git", new=AsyncMock(return_value="")), \
             patch("src.git.operations.get_changed_files",
                   new=AsyncMock(return_value=[])):
            await workflow._auto_approve_no_changes(review_item["id"])
        # The broadcast must include the post-transition item (column=done).
        workflow.notifications.broadcast_item_updated.assert_awaited()
        broadcast_args = [
            call.args[0]
            for call in workflow.notifications.broadcast_item_updated.await_args_list
        ]
        assert any(
            arg.get("id") == review_item["id"] and arg.get("column_name") == "done"
            for arg in broadcast_args
        ), f"expected a done-column broadcast for {review_item['id']}, got {broadcast_args}"

    async def test_clean_merge_path_broadcasts_item_updated(
        self, workflow, db_service, review_item
    ):
        # Regression: the clean merge-success branch in approve_item also used
        # to skip broadcast_item_updated, leaving the card stuck in Review on
        # auto-approve when the agent did produce file changes.
        # Force the file-changes branch and a successful merge.
        await db_service.update_item(review_item["id"], has_file_changes=1)
        workflow.git.merge_agent_work = AsyncMock(
            return_value=(True, "deadbeefdeadbeef")
        )
        workflow.git.base_repo_path = MagicMock(return_value=Path("/tmp"))
        with patch("src.git.operations.run_git", new=AsyncMock(return_value="")), \
             patch("src.git.operations.get_changed_files",
                   new=AsyncMock(return_value=["foo.py"])):
            await workflow.approve_item(review_item["id"])
        workflow.notifications.broadcast_item_updated.assert_awaited()
        broadcast_args = [
            call.args[0]
            for call in workflow.notifications.broadcast_item_updated.await_args_list
        ]
        assert any(
            arg.get("id") == review_item["id"] and arg.get("column_name") == "done"
            for arg in broadcast_args
        ), f"expected a done-column broadcast for {review_item['id']}, got {broadcast_args}"

    async def test_no_op_when_item_left_review(
        self, workflow, db_service, review_item
    ):
        # User cancelled review before the auto-approve task ran.
        await db_service.update_item(review_item["id"], column_name="todo")
        with patch("src.git.operations.run_git", new=AsyncMock(return_value="")), \
             patch("src.git.operations.get_changed_files",
                   new=AsyncMock(return_value=[])):
            await workflow._auto_approve_no_changes(review_item["id"])
        # Should not have moved out of todo.
        updated = await workflow.db.get_item(review_item["id"])
        assert updated["column_name"] == "todo"

    async def test_no_op_when_auto_approve_unset(
        self, workflow, db_service, review_item
    ):
        await db_service.update_item(review_item["id"], auto_approve=0)
        with patch("src.git.operations.run_git", new=AsyncMock(return_value="")), \
             patch("src.git.operations.get_changed_files",
                   new=AsyncMock(return_value=[])):
            await workflow._auto_approve_no_changes(review_item["id"])
        updated = await workflow.db.get_item(review_item["id"])
        # Stays in review for human action.
        assert updated["column_name"] == "review"

    async def test_on_complete_schedules_no_changes_auto_approve(
        self, workflow, db_service, item, tmp_dir
    ):
        """When auto_approve is set and the agent produced no diff, the
        on_complete callback must dispatch _auto_approve_no_changes — not just
        no-op the way it did before."""
        wt = tmp_dir / "worktrees" / "no-changes-2"
        wt.mkdir(parents=True, exist_ok=True)
        await db_service.update_item(
            item["id"],
            column_name="doing",
            status="running",
            auto_approve=1,
            worktree_path=str(wt),
            branch_name="agent/no-changes-2",
            base_branch="main",
        )

        called: list[str] = []

        async def fake_no_changes(iid):
            called.append(iid)

        async def fake_run_review(iid):  # would indicate the wrong branch
            called.append(f"review:{iid}")

        result = AgentResult(success=True, session_id="sess-x")
        with patch("src.git.operations.get_changed_files",
                   new=AsyncMock(return_value=[])), \
             patch.object(workflow, "_auto_approve_no_changes",
                          side_effect=fake_no_changes), \
             patch.object(workflow, "_run_auto_review",
                          side_effect=fake_run_review):
            cb = workflow._create_on_complete_callback(item["id"])
            await cb(result)
            # The two paths are dispatched as background tasks via
            # asyncio.create_task. Yield once so they get a chance to run.
            await asyncio.sleep(0)

        assert called == [item["id"]], (
            f"Expected no-changes path to be dispatched, got {called}"
        )


# ---------------------------------------------------------------------------
# Auto-approve: DIRECT mode (skip review entirely)
# ---------------------------------------------------------------------------

class TestAutoApproveDirect:
    """auto_approve=2 (DIRECT) means: merge as soon as the agent finishes — no
    review-agent pass. The on_complete callback should dispatch
    _auto_approve_direct, and that helper should call approve_item without
    spawning the reviewer."""

    @pytest_asyncio.fixture
    async def review_item_direct(self, db_service, item, tmp_dir):
        wt = tmp_dir / "worktrees" / "direct"
        wt.mkdir(parents=True, exist_ok=True)
        await db_service.update_item(
            item["id"],
            column_name="review",
            status=None,
            auto_approve=2,  # AUTO_APPROVE_DIRECT
            has_file_changes=1,
            worktree_path=str(wt),
            branch_name="agent/direct",
            base_branch="main",
        )
        return item

    async def test_direct_path_calls_approve_item(
        self, workflow, review_item_direct
    ):
        # Patch approve_item to confirm it's invoked. We don't care about its
        # internals here — the no-changes/clean-merge tests cover those.
        with patch.object(
            workflow, "approve_item", new=AsyncMock()
        ) as mock_approve:
            await workflow._auto_approve_direct(review_item_direct["id"])
            mock_approve.assert_awaited_once_with(review_item_direct["id"])

    async def test_direct_path_skips_review_agent(
        self, workflow, review_item_direct
    ):
        # The reviewer must not be spawned in DIRECT mode — that's the whole
        # point of this mode vs auto_approve=1.
        with patch("src.services.workflow_service.run_auto_review",
                   new=AsyncMock()) as mock_review, \
             patch.object(workflow, "approve_item", new=AsyncMock()):
            await workflow._auto_approve_direct(review_item_direct["id"])
            mock_review.assert_not_called()

    async def test_direct_no_op_when_mode_is_review(
        self, workflow, db_service, review_item_direct
    ):
        # Defense in depth: if something dispatched _auto_approve_direct on an
        # item that's actually in REVIEW mode (1), bail out — that path is
        # supposed to go through _run_auto_review, not skip review.
        await db_service.update_item(review_item_direct["id"], auto_approve=1)
        with patch.object(workflow, "approve_item", new=AsyncMock()) as mock_approve:
            await workflow._auto_approve_direct(review_item_direct["id"])
            mock_approve.assert_not_called()

    async def test_direct_no_op_when_item_left_review(
        self, workflow, db_service, review_item_direct
    ):
        # User cancelled before the background task ran.
        await db_service.update_item(review_item_direct["id"], column_name="todo")
        with patch.object(workflow, "approve_item", new=AsyncMock()) as mock_approve:
            await workflow._auto_approve_direct(review_item_direct["id"])
            mock_approve.assert_not_called()

    async def test_on_complete_dispatches_direct_path(
        self, workflow, db_service, item, tmp_dir
    ):
        """auto_approve=2 must route to _auto_approve_direct, NOT to
        _run_auto_review or _auto_approve_no_changes."""
        wt = tmp_dir / "worktrees" / "direct-2"
        wt.mkdir(parents=True, exist_ok=True)
        await db_service.update_item(
            item["id"],
            column_name="doing",
            status="running",
            auto_approve=2,
            worktree_path=str(wt),
            branch_name="agent/direct-2",
            base_branch="main",
        )

        called: list[str] = []

        async def fake_direct(iid):
            called.append(f"direct:{iid}")

        async def fake_review(iid):
            called.append(f"review:{iid}")

        async def fake_no_changes(iid):
            called.append(f"no-changes:{iid}")

        result = AgentResult(success=True, session_id="sess-direct")
        # has_file_changes=1 — pretend the agent did produce a diff. Direct
        # mode should bypass review either way.
        with patch("src.git.operations.get_changed_files",
                   new=AsyncMock(return_value=["foo.py"])), \
             patch.object(workflow, "_auto_approve_direct",
                          side_effect=fake_direct), \
             patch.object(workflow, "_run_auto_review",
                          side_effect=fake_review), \
             patch.object(workflow, "_auto_approve_no_changes",
                          side_effect=fake_no_changes):
            cb = workflow._create_on_complete_callback(item["id"])
            await cb(result)
            await asyncio.sleep(0)

        assert called == [f"direct:{item['id']}"], (
            f"Expected direct path to be dispatched, got {called}"
        )


# ---------------------------------------------------------------------------
# Auto-review badge tracking
# ---------------------------------------------------------------------------

class TestAutoReviewBadgeTracking:
    """The auto-review agent runs outside the regular session manager, so we
    track in-flight reviews in `_auto_reviewing` and broadcast
    `auto_review_changed` events. The UI uses both to render a "Reviewing"
    badge on review-column cards while the diff is being inspected."""

    @pytest_asyncio.fixture
    async def review_item(self, db_service, item, tmp_dir):
        wt = tmp_dir / "worktrees" / "review-badge"
        wt.mkdir(parents=True, exist_ok=True)
        await db_service.update_item(
            item["id"],
            column_name="review",
            status=None,
            auto_approve=1,  # AUTO_APPROVE_REVIEW
            has_file_changes=1,
            worktree_path=str(wt),
            branch_name="agent/review-badge",
            base_branch="main",
        )
        return item

    async def test_run_auto_review_marks_and_unmarks_item(
        self, workflow, review_item
    ):
        # While run_auto_review is awaiting, the item should be in the set;
        # once it resolves, the set should be empty.
        seen_during_review: list[bool] = []

        async def fake_run_review(**kwargs):
            seen_during_review.append(
                review_item["id"] in workflow._auto_reviewing
            )
            return {"approved": True, "comments": [], "summary": "ok", "raw": ""}

        with patch("src.services.workflow_service.run_auto_review",
                   side_effect=fake_run_review), \
             patch("src.git.operations.run_git", new=AsyncMock(return_value="")), \
             patch.object(workflow, "approve_item", new=AsyncMock()):
            await workflow._run_auto_review(review_item["id"])

        assert seen_during_review == [True], (
            "item must be marked as auto-reviewing while run_auto_review runs"
        )
        assert review_item["id"] not in workflow._auto_reviewing, (
            "item must be unmarked once review finishes"
        )

    async def test_run_auto_review_broadcasts_events(
        self, workflow, review_item
    ):
        async def fake_run_review(**kwargs):
            return {"approved": True, "comments": [], "summary": "ok", "raw": ""}

        with patch("src.services.workflow_service.run_auto_review",
                   side_effect=fake_run_review), \
             patch("src.git.operations.run_git", new=AsyncMock(return_value="")), \
             patch.object(workflow, "approve_item", new=AsyncMock()):
            await workflow._run_auto_review(review_item["id"])

        # Two broadcasts: active=True at start, active=False at end.
        review_calls = [
            call for call in workflow.notifications.ws_manager.broadcast.await_args_list
            if call.args and call.args[0] == "auto_review_changed"
        ]
        assert len(review_calls) == 2, (
            f"expected 2 auto_review_changed broadcasts, got {len(review_calls)}: "
            f"{review_calls}"
        )
        assert review_calls[0].args[1] == {
            "item_id": review_item["id"], "active": True,
        }
        assert review_calls[1].args[1] == {
            "item_id": review_item["id"], "active": False,
        }

    async def test_run_auto_review_unmarks_on_agent_failure(
        self, workflow, review_item
    ):
        # If the review agent itself raises, we must still clear the badge —
        # otherwise the UI would show "Reviewing" forever.
        async def boom(**kwargs):
            raise RuntimeError("review agent crashed")

        with patch("src.services.workflow_service.run_auto_review",
                   side_effect=boom), \
             patch("src.git.operations.run_git", new=AsyncMock(return_value="")):
            # _run_auto_review swallows exceptions internally (logs + bails).
            await workflow._run_auto_review(review_item["id"])

        assert review_item["id"] not in workflow._auto_reviewing, (
            "item must be unmarked even when run_auto_review raises"
        )
        # And the active=False broadcast must still go out.
        review_calls = [
            call for call in workflow.notifications.ws_manager.broadcast.await_args_list
            if call.args and call.args[0] == "auto_review_changed"
        ]
        assert any(
            call.args[1] == {"item_id": review_item["id"], "active": False}
            for call in review_calls
        ), "expected an active=False broadcast on failure"
