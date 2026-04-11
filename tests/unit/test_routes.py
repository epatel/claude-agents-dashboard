"""HTTP endpoint tests for src/web/routes.py."""

import pytest
import pytest_asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient, ASGITransport

from src.web.app import create_app
from src.web.websocket import ConnectionManager
from src.database import Database


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_mock_orchestrator():
    mock_orch = MagicMock()
    mock_orch.sessions = {}

    # workflow_service
    mock_orch.workflow_service = MagicMock()
    mock_orch.workflow_service.find_stale_worktrees = AsyncMock(return_value=[])
    mock_orch.workflow_service._yolo_items = set()
    mock_orch.workflow_service.cleanup_stale_worktree = AsyncMock(return_value={"ok": True})

    # db_service
    mock_orch.db_service = MagicMock()
    mock_orch.db_service.get_all_blocked_status = AsyncMock(return_value={})
    mock_orch.db_service.get_item_dependencies = AsyncMock(return_value=[])
    mock_orch.db_service.set_item_dependencies = AsyncMock(return_value=[])
    mock_orch.db_service.get_item = AsyncMock(return_value=None)
    mock_orch.db_service.is_item_blocked = AsyncMock(return_value=False)
    mock_orch.db_service.get_blocking_items = AsyncMock(return_value=[])
    mock_orch.db_service.get_dependent_items = AsyncMock(return_value=[])
    mock_orch.db_service.get_epics = AsyncMock(return_value=[])
    mock_orch.db_service.get_epic_progress = AsyncMock(return_value={})
    mock_orch.db_service.create_epic = AsyncMock(return_value={"id": "epic1", "title": "My Epic", "color": "blue"})
    mock_orch.db_service.update_epic = AsyncMock(return_value={"id": "epic1", "title": "Updated", "color": "blue"})
    mock_orch.db_service.delete_epic = AsyncMock(return_value={"id": "epic1"})
    mock_orch.db_service.update_item = AsyncMock(return_value={"id": "item1", "column_name": "review", "status": None})

    # notification_service
    mock_orch.notification_service = MagicMock()
    mock_orch.notification_service.broadcast_epic_created = AsyncMock()
    mock_orch.notification_service.broadcast_epic_updated = AsyncMock()
    mock_orch.notification_service.broadcast_epic_deleted = AsyncMock()

    # git_service
    mock_orch.git_service = MagicMock()
    mock_orch.git_service.cleanup_worktree_and_branch = AsyncMock()

    # session_service
    mock_orch.session_service = MagicMock()
    mock_orch.session_service.cleanup_session = AsyncMock()

    # ws_manager on orchestrator itself
    mock_orch.ws_manager = MagicMock()
    mock_orch.ws_manager.broadcast = AsyncMock()

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
    async with db.connect() as conn:
        await conn.execute(
            "INSERT INTO items (id, title, description, column_name, position) VALUES (?, ?, ?, ?, ?)",
            ("item001", "Test Item", "A test", "todo", 0),
        )
        await conn.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, app


# ---------------------------------------------------------------------------
# Items CRUD
# ---------------------------------------------------------------------------

class TestListItems:
    @pytest.mark.asyncio
    async def test_list_items_empty(self, client):
        resp = await client.get("/api/items")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_list_items_returns_created_item(self, client_with_item):
        client, app = client_with_item
        resp = await client.get("/api/items")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == "item001"
        assert data[0]["title"] == "Test Item"


class TestCreateItem:
    @pytest.mark.asyncio
    async def test_create_item_returns_201_like(self, client):
        resp = await client.post("/api/items", json={"title": "New Task", "description": "Do something"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "New Task"
        assert data["column_name"] == "todo"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_create_item_default_position(self, client):
        resp = await client.post("/api/items", json={"title": "Item A"})
        assert resp.status_code == 200
        assert resp.json()["position"] == 0

    @pytest.mark.asyncio
    async def test_create_item_increments_position(self, client):
        await client.post("/api/items", json={"title": "Item A"})
        resp = await client.post("/api/items", json={"title": "Item B"})
        assert resp.status_code == 200
        assert resp.json()["position"] == 1

    @pytest.mark.asyncio
    async def test_create_item_with_invalid_epic_returns_400(self, client):
        resp = await client.post("/api/items", json={"title": "X", "epic_id": "nonexistent"})
        assert resp.status_code == 400


class TestUpdateItem:
    @pytest.mark.asyncio
    async def test_update_item_title(self, client_with_item):
        client, app = client_with_item
        resp = await client.patch("/api/items/item001", json={"title": "Updated Title"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated Title"

    @pytest.mark.asyncio
    async def test_update_item_empty_body(self, client_with_item):
        client, app = client_with_item
        resp = await client.patch("/api/items/item001", json={})
        assert resp.status_code == 200
        assert resp.json()["id"] == "item001"


class TestDeleteItem:
    @pytest.mark.asyncio
    async def test_delete_item_calls_orchestrator(self, client_with_item):
        client, app = client_with_item
        resp = await client.delete("/api/items/item001")
        assert resp.status_code == 200
        app.state.orchestrator.delete_item.assert_awaited_once_with("item001")


# ---------------------------------------------------------------------------
# Bulk operations
# ---------------------------------------------------------------------------

class TestArchiveByDate:
    @pytest.mark.asyncio
    async def test_archive_by_date_no_items(self, client):
        resp = await client.post("/api/items/archive-by-date", json={"date": "2024-01-01"})
        assert resp.status_code == 200
        assert resp.json() == {"archived": 0}

    @pytest.mark.asyncio
    async def test_archive_by_date_archives_done_items(self, app_and_db):
        app, db = app_and_db
        async with db.connect() as conn:
            await conn.execute(
                "INSERT INTO items (id, title, description, column_name, position, done_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("done1", "Done Item", "", "done", 0, "2024-06-15T10:00:00"),
            )
            await conn.commit()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/items/archive-by-date", json={"date": "2024-06-15"})
        assert resp.status_code == 200
        assert resp.json()["archived"] == 1


class TestDeleteByDate:
    @pytest.mark.asyncio
    async def test_delete_by_date_no_items(self, client):
        resp = await client.post("/api/items/delete-by-date", json={"date": "2024-01-01", "column_name": "archive"})
        assert resp.status_code == 200
        assert resp.json() == {"deleted": 0}


class TestDeleteByEpic:
    @pytest.mark.asyncio
    async def test_delete_by_epic_no_items(self, client_with_item):
        client, app = client_with_item
        resp = await client.post("/api/items/delete-by-epic", json={"epic_id": "nonexistent"})
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 0


# ---------------------------------------------------------------------------
# Item move
# ---------------------------------------------------------------------------

class TestMoveItem:
    @pytest.mark.asyncio
    async def test_move_item_to_done(self, client_with_item):
        client, app = client_with_item
        resp = await client.post("/api/items/item001/move", json={"column_name": "done", "position": 0})
        assert resp.status_code == 200
        data = resp.json()
        assert data["column_name"] == "done"

    @pytest.mark.asyncio
    async def test_move_item_to_review(self, client_with_item):
        client, app = client_with_item
        resp = await client.post("/api/items/item001/move", json={"column_name": "review", "position": 0})
        assert resp.status_code == 200
        assert resp.json()["column_name"] == "review"

    @pytest.mark.asyncio
    async def test_move_item_to_archive_clears_metadata(self, app_and_db):
        app, db = app_and_db
        async with db.connect() as conn:
            await conn.execute(
                "INSERT INTO items (id, title, description, column_name, position, worktree_path, branch_name) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("wt1", "WT Item", "", "review", 0, "/some/path", "feature-branch"),
            )
            await conn.commit()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/items/wt1/move", json={"column_name": "archive", "position": 0})
        assert resp.status_code == 200
        data = resp.json()
        assert data["worktree_path"] is None


# ---------------------------------------------------------------------------
# Agent actions
# ---------------------------------------------------------------------------

class TestAgentActions:
    @pytest.mark.asyncio
    async def test_start_agent(self, client_with_item):
        client, app = client_with_item
        resp = await client.post("/api/items/item001/start")
        assert resp.status_code == 200
        app.state.orchestrator.start_agent.assert_awaited_once_with("item001")

    @pytest.mark.asyncio
    async def test_cancel_agent(self, client_with_item):
        client, app = client_with_item
        resp = await client.post("/api/items/item001/cancel")
        assert resp.status_code == 200
        app.state.orchestrator.cancel_agent.assert_awaited_once_with("item001")

    @pytest.mark.asyncio
    async def test_pause_agent(self, client_with_item):
        client, app = client_with_item
        resp = await client.post("/api/items/item001/pause")
        assert resp.status_code == 200
        app.state.orchestrator.pause_agent.assert_awaited_once_with("item001")

    @pytest.mark.asyncio
    async def test_resume_agent(self, client_with_item):
        client, app = client_with_item
        resp = await client.post("/api/items/item001/resume")
        assert resp.status_code == 200
        app.state.orchestrator.resume_agent.assert_awaited_once_with("item001")

    @pytest.mark.asyncio
    async def test_retry_agent(self, client_with_item):
        client, app = client_with_item
        resp = await client.post("/api/items/item001/retry")
        assert resp.status_code == 200
        app.state.orchestrator.retry_agent.assert_awaited_once_with("item001")

    @pytest.mark.asyncio
    async def test_approve_item(self, client_with_item):
        client, app = client_with_item
        resp = await client.post("/api/items/item001/approve")
        assert resp.status_code == 200
        app.state.orchestrator.approve_item.assert_awaited_once_with("item001")

    @pytest.mark.asyncio
    async def test_request_changes(self, client_with_item):
        client, app = client_with_item
        resp = await client.post("/api/items/item001/request-changes", json={"comments": ["Fix the bug"]})
        assert resp.status_code == 200
        app.state.orchestrator.request_changes.assert_awaited_once_with("item001", ["Fix the bug"])

    @pytest.mark.asyncio
    async def test_cancel_review(self, client_with_item):
        client, app = client_with_item
        resp = await client.post("/api/items/item001/cancel-review")
        assert resp.status_code == 200
        app.state.orchestrator.cancel_review.assert_awaited_once_with("item001")

    @pytest.mark.asyncio
    async def test_submit_clarification(self, client_with_item):
        client, app = client_with_item
        resp = await client.post("/api/items/item001/clarify", json={"response": "Yes, do it"})
        assert resp.status_code == 200
        app.state.orchestrator.submit_clarification.assert_awaited_once_with("item001", "Yes, do it")

    @pytest.mark.asyncio
    async def test_approve_command_approved(self, client_with_item):
        client, app = client_with_item
        resp = await client.post("/api/items/item001/approve-command", json={"approved": True})
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "approved"

    @pytest.mark.asyncio
    async def test_approve_command_denied(self, client_with_item):
        client, app = client_with_item
        resp = await client.post("/api/items/item001/approve-command", json={"approved": False})
        assert resp.status_code == 200
        assert resp.json()["decision"] == "denied"


# ---------------------------------------------------------------------------
# Work log
# ---------------------------------------------------------------------------

class TestWorkLog:
    @pytest.mark.asyncio
    async def test_get_work_log_empty(self, client_with_item):
        client, app = client_with_item
        resp = await client.get("/api/items/item001/log")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_get_work_log_returns_entries(self, app_and_db):
        app, db = app_and_db
        async with db.connect() as conn:
            await conn.execute(
                "INSERT INTO items (id, title, description, column_name, position) VALUES (?, ?, ?, ?, ?)",
                ("item002", "Item 2", "", "todo", 0),
            )
            await conn.execute(
                "INSERT INTO work_log (item_id, entry_type, content) VALUES (?, ?, ?)",
                ("item002", "system", "Agent started"),
            )
            await conn.commit()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/items/item002/log")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["content"] == "Agent started"


# ---------------------------------------------------------------------------
# Clarification
# ---------------------------------------------------------------------------

class TestClarification:
    @pytest.mark.asyncio
    async def test_get_pending_clarification_none(self, client_with_item):
        client, app = client_with_item
        resp = await client.get("/api/items/item001/clarification")
        assert resp.status_code == 200
        assert resp.json()["prompt"] is None

    @pytest.mark.asyncio
    async def test_get_pending_clarification_with_prompt(self, app_and_db):
        app, db = app_and_db
        async with db.connect() as conn:
            await conn.execute(
                "INSERT INTO items (id, title, description, column_name, position) VALUES (?, ?, ?, ?, ?)",
                ("item003", "Item 3", "", "questions", 0),
            )
            await conn.execute(
                "INSERT INTO clarifications (item_id, prompt) VALUES (?, ?)",
                ("item003", "What should I do?"),
            )
            await conn.commit()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/items/item003/clarification")
        assert resp.status_code == 200
        assert resp.json()["prompt"] == "What should I do?"


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

class TestDependencies:
    @pytest.mark.asyncio
    async def test_get_dependencies(self, client_with_item):
        client, app = client_with_item
        resp = await client.get("/api/items/item001/dependencies")
        assert resp.status_code == 200
        app.state.orchestrator.db_service.get_item_dependencies.assert_awaited_once_with("item001")

    @pytest.mark.asyncio
    async def test_is_blocked_false(self, client_with_item):
        client, app = client_with_item
        resp = await client.get("/api/items/item001/is-blocked")
        assert resp.status_code == 200
        assert resp.json()["blocked"] is False

    @pytest.mark.asyncio
    async def test_get_all_blocked_status(self, client):
        resp = await client.get("/api/items/blocked-status")
        assert resp.status_code == 200
        assert resp.json() == {}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class TestConfig:
    @pytest.mark.asyncio
    async def test_get_config_returns_dict(self, client):
        resp = await client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    @pytest.mark.asyncio
    async def test_get_available_tools(self, client):
        resp = await client.get("/api/config/available-tools")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_update_config(self, client):
        payload = {
            "system_prompt": "You are helpful.",
            "tools": "",
            "model": "claude-opus-4-5",
            "project_context": "",
            "mcp_servers": "",
            "mcp_enabled": False,
            "plugins": "",
            "allowed_commands": "",
            "bash_yolo": False,
            "allowed_builtin_tools": "",
            "flame_enabled": False,
            "flame_intensity_multiplier": 1.0,
        }
        resp = await client.put("/api/config", json=payload)
        assert resp.status_code == 200
        assert resp.json()["system_prompt"] == "You are helpful."


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

class TestNotifications:
    @pytest.mark.asyncio
    async def test_list_notifications_empty(self, client):
        # Clear any notifications that may exist from other tests
        await client.delete("/api/notifications")
        resp = await client.get("/api/notifications")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_clear_notifications(self, client):
        resp = await client.delete("/api/notifications")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    @pytest.mark.asyncio
    async def test_dismiss_notification(self, client):
        # Dismiss a non-existent notification - should still return ok
        resp = await client.delete("/api/notifications/99999")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

class TestStats:
    @pytest.mark.asyncio
    async def test_get_stats_returns_structure(self, client):
        resp = await client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "usage" in data
        assert "activity" in data

    @pytest.mark.asyncio
    async def test_get_websocket_stats(self, client):
        resp = await client.get("/api/websocket/stats")
        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)


# ---------------------------------------------------------------------------
# Epics
# ---------------------------------------------------------------------------

class TestEpics:
    @pytest.mark.asyncio
    async def test_get_epics_empty(self, client):
        resp = await client.get("/api/epics")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_get_epic_colors(self, client):
        resp = await client.get("/api/epics/colors")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_create_epic(self, client):
        resp = await client.post("/api/epics", json={"title": "Sprint 1", "color": "blue"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "My Epic"  # from mock

    @pytest.mark.asyncio
    async def test_update_epic(self, client):
        resp = await client.put("/api/epics/epic1", json={"title": "Updated"})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_update_epic_not_found(self, client_with_item):
        client, app = client_with_item
        app.state.orchestrator.db_service.update_epic = AsyncMock(return_value=None)
        resp = await client.put("/api/epics/missing", json={"title": "X"})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_epic(self, client):
        resp = await client.delete("/api/epics/epic1")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @pytest.mark.asyncio
    async def test_delete_epic_not_found(self, client_with_item):
        client, app = client_with_item
        app.state.orchestrator.db_service.delete_epic = AsyncMock(return_value=None)
        resp = await client.delete("/api/epics/missing")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Shortcuts
# ---------------------------------------------------------------------------

class TestShortcuts:
    @pytest.mark.asyncio
    async def test_list_shortcuts_empty(self, client):
        resp = await client.get("/api/shortcuts")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_create_shortcut(self, client):
        resp = await client.post("/api/shortcuts", json={"name": "Run tests", "command": "pytest"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Run tests"
        assert data["command"] == "pytest"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_list_shortcuts_after_create(self, client):
        await client.post("/api/shortcuts", json={"name": "Build", "command": "make build"})
        resp = await client.get("/api/shortcuts")
        assert resp.status_code == 200
        shortcuts = resp.json()
        assert any(s["name"] == "Build" for s in shortcuts)

    @pytest.mark.asyncio
    async def test_update_shortcut(self, client):
        create_resp = await client.post("/api/shortcuts", json={"name": "Old Name", "command": "echo hi"})
        sc_id = create_resp.json()["id"]
        resp = await client.put(f"/api/shortcuts/{sc_id}", json={"name": "New Name"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"

    @pytest.mark.asyncio
    async def test_update_shortcut_not_found(self, client):
        resp = await client.put("/api/shortcuts/nonexistent", json={"name": "X"})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_shortcut(self, client):
        create_resp = await client.post("/api/shortcuts", json={"name": "Temp", "command": "ls"})
        sc_id = create_resp.json()["id"]
        resp = await client.delete(f"/api/shortcuts/{sc_id}")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    @pytest.mark.asyncio
    async def test_get_shortcut_output_idle(self, client):
        resp = await client.get("/api/shortcuts/nonexistent/output")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "idle"
        assert data["output"] == ""

    @pytest.mark.asyncio
    async def test_stop_shortcut_not_found(self, client):
        resp = await client.post("/api/shortcuts/nonexistent/stop")
        assert resp.status_code == 200
        assert resp.json()["ok"] is False

    @pytest.mark.asyncio
    async def test_reset_shortcut(self, client):
        resp = await client.post("/api/shortcuts/nonexistent/reset")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

class TestSearch:
    @pytest.mark.asyncio
    async def test_search_worklog_short_query(self, client):
        resp = await client.get("/api/search/worklog?q=a")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_search_worklog_empty_query(self, client):
        resp = await client.get("/api/search/worklog")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_search_worklog_with_results(self, app_and_db):
        app, db = app_and_db
        async with db.connect() as conn:
            await conn.execute(
                "INSERT INTO items (id, title, description, column_name, position) VALUES (?, ?, ?, ?, ?)",
                ("item010", "Search Item", "", "todo", 0),
            )
            await conn.execute(
                "INSERT INTO work_log (item_id, entry_type, content) VALUES (?, ?, ?)",
                ("item010", "agent_message", "Agent performed a database migration"),
            )
            await conn.commit()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/search/worklog?q=database")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["item_id"] == "item010"


# ---------------------------------------------------------------------------
# Stale worktree cleanup
# ---------------------------------------------------------------------------

class TestCleanupWorktree:
    @pytest.mark.asyncio
    async def test_cleanup_stale_worktree_ok(self, client_with_item):
        client, app = client_with_item
        resp = await client.post("/api/cleanup/worktree/item001")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    @pytest.mark.asyncio
    async def test_cleanup_stale_worktree_error(self, client_with_item):
        client, app = client_with_item
        app.state.orchestrator.workflow_service.cleanup_stale_worktree = AsyncMock(
            side_effect=Exception("not found")
        )
        resp = await client.post("/api/cleanup/worktree/item001")
        assert resp.status_code == 200
        assert resp.json()["ok"] is False
        assert "not found" in resp.json()["error"]


# ---------------------------------------------------------------------------
# Yolo items
# ---------------------------------------------------------------------------

class TestYoloItems:
    @pytest.mark.asyncio
    async def test_get_yolo_items_empty(self, client):
        resp = await client.get("/api/yolo-items")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_get_yolo_items_with_entries(self, client_with_item):
        client, app = client_with_item
        app.state.orchestrator.workflow_service._yolo_items = {"item001", "item002"}
        resp = await client.get("/api/yolo-items")
        assert resp.status_code == 200
        data = resp.json()
        assert set(data) == {"item001", "item002"}


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------

class TestAttachments:
    @pytest.mark.asyncio
    async def test_list_attachments_empty(self, client_with_item):
        client, app = client_with_item
        resp = await client.get("/api/items/item001/attachments")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_upload_attachment(self, client_with_item):
        import base64
        client, app = client_with_item
        # minimal 1x1 png
        png_bytes = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
            b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
            b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        b64 = "data:image/png;base64," + base64.b64encode(png_bytes).decode()
        resp = await client.post(
            "/api/items/item001/attachments",
            json={"item_id": "item001", "filename": "test.png", "data": b64},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["item_id"] == "item001"
        assert data["filename"] == "test.png"

    @pytest.mark.asyncio
    async def test_delete_attachment(self, client_with_item):
        import base64
        client, app = client_with_item
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        b64 = base64.b64encode(png_bytes).decode()
        upload_resp = await client.post(
            "/api/items/item001/attachments",
            json={"item_id": "item001", "filename": "del.png", "data": b64},
        )
        att_id = upload_resp.json()["id"]
        resp = await client.delete(f"/api/attachments/{att_id}")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}


# ---------------------------------------------------------------------------
# Diff / file content
# ---------------------------------------------------------------------------

class TestDiff:
    @pytest.mark.asyncio
    async def test_get_diff_no_branch(self, client_with_item):
        client, app = client_with_item
        resp = await client.get("/api/items/item001/diff")
        assert resp.status_code == 200
        data = resp.json()
        assert data["diff"] == ""
        assert data["files"] == []
