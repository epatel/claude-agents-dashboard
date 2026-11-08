"""HTTP endpoint tests for src/web/routes.py."""

import pytest
from unittest.mock import AsyncMock, patch

from tests.unit.route_fixtures import app_and_db, client, client_with_item  # noqa: F401  (pytest fixtures)
from tests.unit.route_fixtures import get_json, item_row, request, seed, seed_logged_item


# ---------------------------------------------------------------------------
# Items CRUD
# ---------------------------------------------------------------------------

class TestCreateAgentTodo:
    @pytest.mark.asyncio
    async def test_delegates_to_orchestrator_with_full_kwargs(self, client_with_item):
        client, app = client_with_item
        app.state.orchestrator.create_agent_todo = AsyncMock(
            return_value={"id": "new1", "title": "Follow-up", "autostart_scheduled": True})
        resp = await client.post("/api/items/item001/agent-todos", json={
            "title": "Follow-up", "description": "d", "requires": ["dep1"],
            "autostart": True, "auto_approve": 1, "use_chrome": True,
        })
        assert resp.status_code == 200
        assert resp.json()["id"] == "new1"
        app.state.orchestrator.create_agent_todo.assert_awaited_once_with(
            "item001", title="Follow-up", description="d", epic_id=None,
            requires=["dep1"], autostart=True, auto_approve=1, use_chrome=True,
        )

    @pytest.mark.asyncio
    async def test_unknown_creator_item_404s(self, client):
        resp = await client.post("/api/items/nope/agent-todos", json={"title": "X"})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_minimal_body_uses_defaults(self, client_with_item):
        client, app = client_with_item
        app.state.orchestrator.create_agent_todo = AsyncMock(
            return_value={"id": "new2", "title": "Simple"})
        resp = await client.post("/api/items/item001/agent-todos", json={"title": "Simple"})
        assert resp.status_code == 200
        kwargs = app.state.orchestrator.create_agent_todo.await_args.kwargs
        assert kwargs["requires"] == []
        assert kwargs["autostart"] is False
        assert kwargs["auto_approve"] == 0


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
        await seed(db, item_row("done1", "Done Item", "done", done_at="2024-06-15T10:00:00"))
        resp = await request(app, "POST", "/api/items/archive-by-date", json={"date": "2024-06-15"})
        assert resp.status_code == 200
        assert resp.json()["archived"] == 1


class TestArchiveByEpic:
    @pytest.mark.asyncio
    async def test_archive_by_epic_no_items(self, client):
        resp = await client.post("/api/items/archive-by-epic", json={"epic_id": "missing"})
        assert resp.status_code == 200
        assert resp.json() == {"archived": 0}

    @pytest.mark.asyncio
    async def test_archive_by_epic_archives_only_done(self, app_and_db):
        app, db = app_and_db
        await seed(db,
            ("epics", {"id": "epicA", "title": "Epic A", "color": "blue", "position": 0}),
            item_row("d1", "Done 1", "done", epic_id="epicA"),
            item_row("d2", "Done 2", "done", position=1, epic_id="epicA"),
            item_row("t1", "Todo", epic_id="epicA"),
        )
        resp = await request(app, "POST", "/api/items/archive-by-epic", json={"epic_id": "epicA"})
        assert resp.status_code == 200
        assert resp.json()["archived"] == 2
        async with db.connect() as conn:
            cursor = await conn.execute("SELECT id, column_name FROM items WHERE epic_id = 'epicA' ORDER BY id")
            rows = await cursor.fetchall()
        cols = {r[0]: r[1] for r in rows}
        assert cols == {"d1": "archive", "d2": "archive", "t1": "todo"}


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
        await seed(db,
            item_row("wt1", "WT Item", "review", worktree_path="/some/path", branch_name="feature-branch"),
        )
        resp = await request(app, "POST", "/api/items/wt1/move", json={"column_name": "archive", "position": 0})
        assert resp.status_code == 200
        data = resp.json()
        assert data["worktree_path"] is None

    @pytest.mark.asyncio
    async def test_move_to_done_triggers_dependent_auto_start(self, client_with_item):
        """Regression: dragging a required item directly to Done must fire the
        auto-start hook, not just the merge pipeline. Previously dependents
        with auto_start=true sat in todo forever after a manual drop."""
        client, app = client_with_item
        resp = await client.post(
            "/api/items/item001/move", json={"column_name": "done", "position": 0}
        )
        assert resp.status_code == 200
        app.state.orchestrator.workflow_service.notify_and_auto_start_dependents.assert_awaited_once_with(
            "item001"
        )

    @pytest.mark.asyncio
    async def test_move_to_archive_triggers_dependent_auto_start(self, client_with_item):
        client, app = client_with_item
        resp = await client.post(
            "/api/items/item001/move", json={"column_name": "archive", "position": 0}
        )
        assert resp.status_code == 200
        app.state.orchestrator.workflow_service.notify_and_auto_start_dependents.assert_awaited_once_with(
            "item001"
        )

    @pytest.mark.asyncio
    async def test_move_to_review_does_not_trigger_auto_start(self, client_with_item):
        """Auto-start hook should only fire on terminal columns (done/archive)."""
        client, app = client_with_item
        resp = await client.post(
            "/api/items/item001/move", json={"column_name": "review", "position": 0}
        )
        assert resp.status_code == 200
        app.state.orchestrator.workflow_service.notify_and_auto_start_dependents.assert_not_awaited()


# ---------------------------------------------------------------------------
# Agent actions
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
        await seed_logged_item(db, item_row("item002", "Item 2"), "system", "Agent started")
        data = await get_json(app, "/api/items/item002/log")
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
        await seed(db,
            item_row("item003", "Item 3", "questions"),
            ("clarifications", {"item_id": "item003", "prompt": "What should I do?"}),
        )
        resp = await request(app, "GET", "/api/items/item003/clarification")
        assert resp.status_code == 200
        body = resp.json()
        assert body["prompt"] == "What should I do?"
        # The endpoint returns the full row, so the new `context` key must
        # be present (even when no context was stored).
        assert "context" in body
        assert body["context"] is None

    @pytest.mark.asyncio
    async def test_get_pending_clarification_returns_context(self, app_and_db):
        app, db = app_and_db
        await seed(db,
            item_row("item004", "Item 4", "questions"),
            ("clarifications", {"item_id": "item004", "prompt": "Approve plan?", "context": "Considered options A and B; chose A."}),
        )
        resp = await request(app, "GET", "/api/items/item004/clarification")
        assert resp.status_code == 200
        body = resp.json()
        assert body["prompt"] == "Approve plan?"
        assert body["context"] == "Considered options A and B; chose A."


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
        await seed_logged_item(db, item_row("item010", "Search Item"), "agent_message",
                               "Agent performed a database migration")
        data = await get_json(app, "/api/search/worklog?q=database")
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
# Auto-reviewing items
# ---------------------------------------------------------------------------


class TestAutoReviewingItems:
    @pytest.mark.asyncio
    async def test_get_auto_reviewing_items_empty(self, client):
        resp = await client.get("/api/auto-reviewing-items")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_get_auto_reviewing_items_with_entries(self, client_with_item):
        client, app = client_with_item
        app.state.orchestrator.workflow_service._auto_reviewing = {"item001", "item002"}
        resp = await client.get("/api/auto-reviewing-items")
        assert resp.status_code == 200
        data = resp.json()
        assert set(data) == {"item001", "item002"}


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------


class TestItemDetail:
    @pytest.mark.asyncio
    async def test_get_item_detail_returns_html(self, client_with_item):
        client, app = client_with_item
        resp = await client.get("/api/items/item001")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Test Item" in resp.text

    @pytest.mark.asyncio
    async def test_get_item_detail_not_found(self, client):
        resp = await client.get("/api/items/nonexistent")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_item_detail_includes_work_log(self, app_and_db):
        app, db = app_and_db
        await seed_logged_item(db, item_row("item-log", "Logged Item", "done", description="desc"),
                               "agent_message", "Completed the migration")
        resp = await request(app, "GET", "/api/items/item-log")
        assert resp.status_code == 200
        assert "Completed the migration" in resp.text

    @pytest.mark.asyncio
    async def test_get_item_detail_shows_no_log_message(self, client_with_item):
        client, app = client_with_item
        resp = await client.get("/api/items/item001")
        assert "No work log entries" in resp.text

    @pytest.mark.asyncio
    async def test_get_item_detail_escapes_html(self, app_and_db):
        app, db = app_and_db
        await seed(db, item_row("item-xss", "<script>alert(1)</script>", description="desc"))
        resp = await request(app, "GET", "/api/items/item-xss")
        assert resp.status_code == 200
        assert "<script>" not in resp.text
        assert "&lt;script&gt;" in resp.text

    @pytest.mark.asyncio
    async def test_get_item_detail_includes_commit_message(self, app_and_db):
        app, db = app_and_db
        await seed(db,
            item_row("item-cm", "With Commit", "done", description="desc", commit_message="Fix the bug"),
        )
        resp = await request(app, "GET", "/api/items/item-cm")
        assert "Fix the bug" in resp.text


# ---------------------------------------------------------------------------
# Start copy agent
# ---------------------------------------------------------------------------


class TestCreateItemStartCopy:
    @pytest.mark.asyncio
    async def test_create_item_with_start_copy_true(self, client):
        resp = await client.post("/api/items", json={
            "title": "Copy Task",
            "description": "A task with start_copy",
            "start_copy": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["start_copy"] == 1

    @pytest.mark.asyncio
    async def test_create_item_start_copy_defaults_false(self, client):
        resp = await client.post("/api/items", json={
            "title": "Normal Task",
            "description": "A normal task",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["start_copy"] == 0


# ---------------------------------------------------------------------------
# Default values for new projects / items
# ---------------------------------------------------------------------------


class TestDefaultValues:
    """Verify that new items and fresh configs use the constants from constants.py."""

    @pytest.mark.asyncio
    async def test_create_item_default_model(self, client):
        """A new item created without a model stores NULL ("Default").

        It must NOT bake in DEFAULT_MODEL — that would shadow the configured
        global default model at spawn time (resolution is
        `item.model or config.model`). A NULL here means "use the global
        default", which is what the form's "Default" option intends.
        """
        resp = await client.post("/api/items", json={"title": "No model specified"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["model"] is None

    @pytest.mark.asyncio
    async def test_create_item_explicit_model_overrides_default(self, client):
        """An explicit model in the request should override the default."""
        resp = await client.post("/api/items", json={
            "title": "Custom model",
            "model": "claude-haiku-4-5-20251001",
        })
        assert resp.status_code == 200
        assert resp.json()["model"] == "claude-haiku-4-5-20251001"

    @pytest.mark.asyncio
    async def test_config_default_model(self, client):
        """Fresh config should use DEFAULT_MODEL."""
        from src.constants import DEFAULT_MODEL
        resp = await client.get("/api/config")
        assert resp.status_code == 200
        assert resp.json()["model"] == DEFAULT_MODEL

    @pytest.mark.asyncio
    async def test_config_default_ollama_url(self, client):
        """Fresh config should use DEFAULT_OLLAMA_BASE_URL."""
        from src.constants import DEFAULT_OLLAMA_BASE_URL
        resp = await client.get("/api/config")
        assert resp.status_code == 200
        assert resp.json()["ollama_base_url"] == DEFAULT_OLLAMA_BASE_URL


# ---------------------------------------------------------------------------
# Retry merge
# ---------------------------------------------------------------------------
