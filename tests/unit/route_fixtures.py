"""Shared fixtures and helpers for the route tests (real DB, mocked orchestrator).

A plain module, not a conftest: test modules import the fixtures they need
explicitly, so names like ``client`` don't leak into other modules.
"""

import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock

from httpx import AsyncClient, ASGITransport

from src.web.app import create_app
from src.web.websocket import ConnectionManager
from src.database import Database


async def seed(db, *rows):
    """Insert each (table, {column: value}) row, then commit."""
    async with db.connect() as conn:
        for table, values in rows:
            columns = ", ".join(values)
            marks = ", ".join("?" * len(values))
            await conn.execute(f"INSERT INTO {table} ({columns}) VALUES ({marks})", tuple(values.values()))
        await conn.commit()


def item_row(item_id, title, column="todo", **fields):
    """A seed() row for the items table (description "" and position 0 unless given in ``fields``)."""
    values = {"id": item_id, "title": title, "description": "", "column_name": column, "position": 0}
    values.update(fields)
    return ("items", values)


def log_row(item_id, entry_type, content):
    """A seed() row for the work_log table."""
    return ("work_log", {"item_id": item_id, "entry_type": entry_type, "content": content})


async def seed_logged_item(db, item, entry_type, content):
    """Seed ``item`` (an item_row) with a single work-log entry."""
    await seed(db, item, log_row(item[1]["id"], entry_type, content))


async def request(app, method, path, **kwargs):
    """One HTTP request to ``app`` through a short-lived client."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        return await c.request(method, path, **kwargs)


async def get_json(app, path):
    """GET ``path`` from ``app``, asserting HTTP 200; returns the JSON body."""
    resp = await request(app, "GET", path)
    assert resp.status_code == 200
    return resp.json()


def _mock_workflow_service():
    """Mock workflow_service."""
    svc = MagicMock()
    svc.find_stale_worktrees = AsyncMock(return_value=[])
    svc._yolo_items = set()
    svc._auto_reviewing = set()
    svc.cleanup_stale_worktree = AsyncMock(return_value={"ok": True})
    svc.notify_and_auto_start_dependents = AsyncMock()
    return svc


def _mock_db_service():
    """Mock db_service."""
    svc = MagicMock()
    svc.get_all_blocked_status = AsyncMock(return_value={})
    svc.get_item_dependencies = AsyncMock(return_value=[])
    svc.set_item_dependencies = AsyncMock(return_value=[])
    svc.get_item = AsyncMock(return_value=None)
    svc.is_item_blocked = AsyncMock(return_value=False)
    svc.get_blocking_items = AsyncMock(return_value=[])
    svc.get_dependent_items = AsyncMock(return_value=[])
    svc.get_epics = AsyncMock(return_value=[])
    svc.get_epic_progress = AsyncMock(return_value={})
    svc.create_epic = AsyncMock(return_value={"id": "epic1", "title": "My Epic", "color": "blue"})
    svc.update_epic = AsyncMock(return_value={"id": "epic1", "title": "Updated", "color": "blue"})
    svc.delete_epic = AsyncMock(return_value={"id": "epic1"})
    svc.update_item = AsyncMock(return_value={"id": "item1", "column_name": "review", "status": None})
    return svc


def _mock_item_repository():
    """Mock item_repository (Phase 2.1+ — read/write facade over db_service)."""
    svc = MagicMock()
    svc.transition = AsyncMock(
        return_value={"id": "item1", "column_name": "review", "status": None}
    )
    svc.get = AsyncMock(
        return_value={
            "id": "item1", "column_name": "todo", "status": None,
            "worktree_path": "/some/path", "branch_name": "feature",
        }
    )

    # move_to_column needs to reflect inputs so route tests can assert
    # against realistic response shapes (column_name == requested,
    # worktree cleared on done/archive, etc.).
    async def _mock_move_to_column(item_id, target_column, position):
        return {
            "id": item_id,
            "column_name": target_column,
            "status": None,
            "position": position,
            "worktree_path": None if target_column in ("done", "archive") else "/some/path",
            "branch_name": None if target_column in ("done", "archive") else "feature",
        }
    svc.move_to_column = AsyncMock(side_effect=_mock_move_to_column)
    svc.shift_positions = AsyncMock()
    return svc


def _mock_epic_repository():
    """Mock epic_repository (Phase 2.6 — CRUD facade over db_service)."""
    svc = MagicMock()
    svc.list_all = AsyncMock(return_value=[])
    svc.create = AsyncMock(
        return_value={"id": "epic1", "title": "My Epic", "color": "blue"}
    )
    svc.update = AsyncMock(
        return_value={"id": "epic1", "title": "Updated", "color": "blue"}
    )
    svc.delete = AsyncMock(
        return_value={"id": "epic1", "title": "Deleted", "color": "blue"}
    )
    return svc


def _mock_notification_service():
    """Mock notification_service."""
    svc = MagicMock()
    svc.broadcast_epic_created = AsyncMock()
    svc.broadcast_epic_updated = AsyncMock()
    svc.broadcast_epic_deleted = AsyncMock()
    return svc


def _mock_git_service():
    """Mock git_service."""
    svc = MagicMock()
    svc.cleanup_worktree_and_branch = AsyncMock()
    return svc


def _mock_session_service():
    """Mock session_service."""
    svc = MagicMock()
    svc.cleanup_session = AsyncMock()
    return svc


def _mock_ws_manager():
    """Mock ws_manager on orchestrator itself."""
    svc = MagicMock()
    svc.broadcast = AsyncMock()
    return svc


def _mock_graph_service():
    """Mock graph_service (graphify)."""
    svc = MagicMock()
    svc._lock = MagicMock()
    svc._lock.locked.return_value = False
    svc.status = AsyncMock(return_value={
        "installed_version": "0.8.33", "latest_version": "0.8.33",
        "building": False, "graph": {"exists": False}, "graph_dir": "/x/graphify-out",
    })
    svc.build = AsyncMock(return_value={"ok": True, "graph": {}})
    svc.install = AsyncMock(return_value={"ok": True, "version": "0.8.33"})
    svc.query = AsyncMock(return_value={"ok": True, "answer": "ans"})
    return svc


def _mock_skills_service():
    """Mock skills_service."""
    svc = MagicMock()
    svc.list_installed = MagicMock(
        return_value=[{"name": "docx", "description": "Make docx", "enabled": False}]
    )
    svc.browse = AsyncMock(
        return_value=[{"name": "docx", "description": "Make docx", "spec": "anthropics/skills/skills/docx"}]
    )
    svc.install = AsyncMock(return_value={"ok": True, "name": "docx"})
    svc.remove = AsyncMock(return_value={"ok": True, "name": "docx"})
    svc.discover = AsyncMock(return_value=[
        {"name": "docx", "path": "skills/docx", "description": "d", "spec": "anthropics/skills/skills/docx@main"},
        {"name": "pdf", "path": "skills/pdf", "description": "p", "spec": "anthropics/skills/skills/pdf@main"},
    ])
    return svc


def _make_mock_orchestrator():
    mock_orch = MagicMock()
    mock_orch.sessions = {}

    mock_orch.workflow_service = _mock_workflow_service()
    mock_orch.db_service = _mock_db_service()
    mock_orch.item_repository = _mock_item_repository()
    mock_orch.epic_repository = _mock_epic_repository()
    mock_orch.notification_service = _mock_notification_service()
    mock_orch.git_service = _mock_git_service()
    mock_orch.session_service = _mock_session_service()
    mock_orch.ws_manager = _mock_ws_manager()

    # agent actions
    mock_orch.start_agent = AsyncMock(return_value={"status": "started"})
    mock_orch.start_copy_agent = AsyncMock(return_value={"status": "started"})
    mock_orch.cancel_agent = AsyncMock(return_value={"status": "cancelled"})
    mock_orch.pause_agent = AsyncMock(return_value={"status": "paused"})
    mock_orch.resume_agent = AsyncMock(return_value={"status": "running"})
    mock_orch.retry_agent = AsyncMock(return_value={"status": "running"})
    mock_orch.approve_item = AsyncMock(return_value={"status": "done"})
    mock_orch.request_changes = AsyncMock(return_value={"status": "todo"})
    mock_orch.cancel_review = AsyncMock(return_value={"status": "todo"})
    mock_orch.submit_clarification = AsyncMock(return_value={"status": "ok"})
    mock_orch.delete_item = AsyncMock(return_value={"ok": True})
    mock_orch.shutdown = AsyncMock()

    mock_orch.graph_service = _mock_graph_service()
    mock_orch.skills_service = _mock_skills_service()
    return mock_orch


@pytest_asyncio.fixture
async def app_and_db(tmp_path):
    """Create app with real DB but mocked orchestrator, bypassing lifespan."""
    target = tmp_path / "target"
    target.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # Create and initialize real DB
    db = Database(data_dir / "dashboard.db")
    await db.initialize()

    app = create_app(target_project=target, data_dir=data_dir)

    # Override state to skip lifespan
    app.state.db = db
    ws_manager = ConnectionManager()
    app.state.ws_manager = ws_manager
    mock_orch = _make_mock_orchestrator()
    mock_orch.ws_manager = ws_manager
    app.state.orchestrator = mock_orch

    return app, db


@pytest_asyncio.fixture
async def client(app_and_db):
    app, db = app_and_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def client_with_item(app_and_db):
    """Client with a pre-created item in the DB."""
    app, db = app_and_db
    await seed(db, item_row("item001", "Test Item", description="A test"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, app
