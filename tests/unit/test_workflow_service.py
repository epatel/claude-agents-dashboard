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
    async def test_pause_sets_paused_status(self, workflow, item):
        result = await workflow.pause_agent(item["id"])
        assert result["status"] == "paused"

    async def test_pause_stores_session_id(self, workflow, item):
        result = await workflow.pause_agent(item["id"])
        assert result["session_id"] == "sess-paused-id"

    async def test_pause_broadcasts_update(self, workflow, item):
        await workflow.pause_agent(item["id"])
        workflow.notifications.broadcast_item_updated.assert_awaited()

    async def test_pause_no_session_id_still_pauses(self, workflow, item):
        workflow.sessions.pause_session = AsyncMock(return_value=None)
        result = await workflow.pause_agent(item["id"])
        assert result["status"] == "paused"


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
# _notify_and_auto_start_dependents
# ---------------------------------------------------------------------------

class TestNotifyAndAutoStartDependents:
    async def test_no_dependents_does_nothing(self, workflow, item):
        # Should not raise, no broadcast
        await workflow._notify_and_auto_start_dependents(item["id"])
        workflow.notifications.ws_manager.broadcast.assert_not_awaited()

    async def test_broadcasts_dependencies_resolved(self, workflow, db_service):
        parent = await db_service.create_todo_item("Parent", "p")
        child = await db_service.create_todo_item("Child", "c")
        await db_service.set_item_dependencies(child["id"], [parent["id"]])

        await workflow._notify_and_auto_start_dependents(parent["id"])
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

        await workflow._notify_and_auto_start_dependents(parent["id"])
        # start_agent should have been called for the unblocked child
        workflow.sessions.create_session.assert_awaited()


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
    async def test_success_moves_to_review(self, workflow, item):
        result = AgentResult(success=True, session_id="sess-abc")
        cb = workflow._create_on_complete_callback(item["id"])
        await cb(result)
        updated = await workflow.db.get_item(item["id"])
        assert updated["column_name"] == "review"

    async def test_failure_sets_failed_status(self, workflow, item):
        result = AgentResult(success=False, error="something went wrong", session_id="sess-fail")
        cb = workflow._create_on_complete_callback(item["id"])
        await cb(result)
        updated = await workflow.db.get_item(item["id"])
        assert updated["status"] == "failed"

    async def test_success_stores_commit_message(self, workflow, item):
        workflow.sessions.get_commit_message = MagicMock(return_value="feat: my commit")
        result = AgentResult(success=True, session_id="sess-abc")
        cb = workflow._create_on_complete_callback(item["id"])
        await cb(result)
        updated = await workflow.db.get_item(item["id"])
        assert updated["commit_message"] == "feat: my commit"

    async def test_removes_session_on_complete(self, workflow, item):
        result = AgentResult(success=True, session_id="sess-abc")
        cb = workflow._create_on_complete_callback(item["id"])
        await cb(result)
        workflow.sessions.remove_session.assert_called_with(item["id"])

    async def test_clears_yolo_tracking_on_complete(self, workflow, item):
        workflow._yolo_items.add(item["id"])
        result = AgentResult(success=True, session_id="sess-abc")
        cb = workflow._create_on_complete_callback(item["id"])
        await cb(result)
        assert item["id"] not in workflow._yolo_items

    async def test_broadcasts_item_updated_on_success(self, workflow, item):
        result = AgentResult(success=True, session_id="sess-abc")
        cb = workflow._create_on_complete_callback(item["id"])
        await cb(result)
        workflow.notifications.broadcast_item_updated.assert_awaited()


# ---------------------------------------------------------------------------
# Callback: _create_on_error_callback
# ---------------------------------------------------------------------------

class TestOnErrorCallback:
    async def test_sets_failed_status(self, workflow, item):
        cb = workflow._create_on_error_callback(item["id"])
        await cb("some error")
        updated = await workflow.db.get_item(item["id"])
        assert updated["status"] == "failed"

    async def test_removes_session(self, workflow, item):
        cb = workflow._create_on_error_callback(item["id"])
        await cb("error")
        workflow.sessions.remove_session.assert_called_with(item["id"])

    async def test_broadcasts_item_updated(self, workflow, item):
        cb = workflow._create_on_error_callback(item["id"])
        await cb("error")
        workflow.notifications.broadcast_item_updated.assert_awaited()

    async def test_clears_yolo_on_error(self, workflow, item):
        workflow._yolo_items.add(item["id"])
        cb = workflow._create_on_error_callback(item["id"])
        await cb("error")
        assert item["id"] not in workflow._yolo_items


# ---------------------------------------------------------------------------
# Callback: _create_on_clarify_callback
# ---------------------------------------------------------------------------

class TestOnClarifyCallback:
    async def test_moves_item_to_questions(self, workflow, item):
        cb = workflow._create_on_clarify_callback(item["id"])

        # Pre-set the response so event.wait() returns immediately
        workflow._clarify_responses[item["id"]] = "answer"
        pre_set_event = asyncio.Event()
        pre_set_event.set()

        original_event = asyncio.Event
        def make_pre_set_event():
            return pre_set_event
        with patch("asyncio.Event", side_effect=make_pre_set_event):
            response = await cb("What color?", None)
        updated = await workflow.db.get_item(item["id"])
        assert updated["column_name"] == "doing"  # moved back after response

    async def test_returns_user_response(self, workflow, item):
        cb = workflow._create_on_clarify_callback(item["id"])

        workflow._clarify_responses[item["id"]] = "blue"
        pre_set_event = asyncio.Event()
        pre_set_event.set()
        with patch("asyncio.Event", return_value=pre_set_event):
            response = await cb("What color?", ["red", "blue"])
        assert response == "blue"

    async def test_broadcasts_clarification_requested(self, workflow, item):
        cb = workflow._create_on_clarify_callback(item["id"])

        workflow._clarify_responses[item["id"]] = "yes"
        pre_set_event = asyncio.Event()
        pre_set_event.set()
        with patch("asyncio.Event", return_value=pre_set_event):
            await cb("Continue?", ["yes", "no"])
        workflow.notifications.broadcast_clarification_requested.assert_awaited()


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

    async def test_empty_board_returns_string(self, workflow):
        cb = workflow._create_on_view_board_callback()
        result = await cb()
        assert isinstance(result, str)


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
