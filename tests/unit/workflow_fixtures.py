"""Shared WorkflowService fixtures and helpers (real DB, mocked git/sessions).

A plain module, not a conftest: test modules import the fixtures they need
explicitly, so names like ``db`` / ``item`` don't leak into other modules.
"""

import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio

from src.database import Database
from src.services.database_service import DatabaseService
from src.services.git_service import GitService
from src.services.notification_service import NotificationService
from src.services.session_service import SessionService
from src.services.workflow_service import WorkflowService


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


def _mock_git(tmp_dir):
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
    return git_service


def _mock_notifications():
    ws_manager = MagicMock()
    ws_manager.broadcast = AsyncMock()
    notif_service = NotificationService(ws_manager)
    for name in (
        "broadcast_item_updated", "broadcast_item_created", "broadcast_item_deleted",
        "broadcast_agent_log", "broadcast_clarification_requested", "broadcast_epic_created",
    ):
        setattr(notif_service, name, AsyncMock())
    return notif_service


def _mock_sessions():
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
    return session_service


@pytest_asyncio.fixture
async def workflow(db_service, tmp_dir):
    yield WorkflowService(
        db_service, _mock_git(tmp_dir), _mock_notifications(), _mock_sessions(), tmp_dir
    )


@pytest_asyncio.fixture
async def item(db_service):
    """A base todo item."""
    return await db_service.create_todo_item("Test Task", "Do something useful")


@pytest_asyncio.fixture
async def running_item(db_service, item):
    """The base item moved to RUNNING (doing/running).

    Pause, ask (RUNNING -> CLARIFY), on_complete and on_error (FAIL) are only
    valid from an active agent, so mirror production by starting there.
    """
    await db_service.update_item(item["id"], column_name="doing", status="running")
    return item


async def stage_item(workflow, item_id, worktree, **fields):
    """Create ``<tmp_dir>/worktrees/<worktree>`` and point the item at it."""
    wt = workflow.git.worktree_dir / worktree
    wt.mkdir(parents=True, exist_ok=True)
    await workflow.db.update_item(item_id, worktree_path=str(wt), **fields)
    return wt


async def fetch_row(workflow, sql, item_id):
    """Run ``sql`` with ``item_id`` as its only parameter; return the first row."""
    async with workflow.db.db.connect() as conn:
        cursor = await conn.execute(sql, (item_id,))
        return await cursor.fetchone()


async def work_log_row(workflow, item_id, columns="content", entry_type=None):
    """First work_log row for the item, optionally filtered by entry type."""
    sql = f"SELECT {columns} FROM work_log WHERE item_id = ?"
    if entry_type:
        sql += f" AND entry_type = '{entry_type}'"
    return await fetch_row(workflow, sql, item_id)


@contextmanager
def fake_repo(changed_files=()):
    """Patch run_git (clean status) and get_changed_files."""
    with patch("src.git.operations.run_git", new=AsyncMock(return_value="")), \
         patch("src.git.operations.get_changed_files",
               new=AsyncMock(return_value=list(changed_files))):
        yield
