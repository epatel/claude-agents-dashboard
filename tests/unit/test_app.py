"""Unit tests for src/web/app.py — factory, middleware, and stale worktree check."""

import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

from src.web.app import (
    _audit_item_state_encodings,
    _build_cors_origins,
    _check_stale_worktrees,
    SecurityHeadersMiddleware,
    create_app,
)
from src.config import DEFAULT_HOST, DEFAULT_PORT, MAX_PORT_TRIES
from src.database import Database


# ---------------------------------------------------------------------------
# _build_cors_origins
# ---------------------------------------------------------------------------

class TestBuildCorsOrigins:
    def test_length_is_two_per_port(self):
        origins = _build_cors_origins()
        assert len(origins) == MAX_PORT_TRIES * 2

    def test_includes_default_port(self):
        origins = _build_cors_origins()
        assert f"http://{DEFAULT_HOST}:{DEFAULT_PORT}" in origins
        assert f"http://localhost:{DEFAULT_PORT}" in origins

    def test_includes_last_port(self):
        last_port = DEFAULT_PORT + MAX_PORT_TRIES - 1
        origins = _build_cors_origins()
        assert f"http://{DEFAULT_HOST}:{last_port}" in origins
        assert f"http://localhost:{last_port}" in origins

    def test_does_not_include_port_beyond_range(self):
        beyond = DEFAULT_PORT + MAX_PORT_TRIES
        origins = _build_cors_origins()
        assert f"http://localhost:{beyond}" not in origins

    def test_all_entries_are_http(self):
        for origin in _build_cors_origins():
            assert origin.startswith("http://")


# ---------------------------------------------------------------------------
# SecurityHeadersMiddleware
# ---------------------------------------------------------------------------

class TestSecurityHeadersMiddleware:
    @pytest.mark.asyncio
    async def test_adds_x_content_type_options(self):
        app = MagicMock()
        middleware = SecurityHeadersMiddleware(app)

        mock_response = MagicMock()
        mock_response.headers = {}
        call_next = AsyncMock(return_value=mock_response)
        request = MagicMock()

        response = await middleware.dispatch(request, call_next)
        assert response.headers["X-Content-Type-Options"] == "nosniff"

    @pytest.mark.asyncio
    async def test_adds_x_frame_options(self):
        app = MagicMock()
        middleware = SecurityHeadersMiddleware(app)

        mock_response = MagicMock()
        mock_response.headers = {}
        call_next = AsyncMock(return_value=mock_response)
        request = MagicMock()

        response = await middleware.dispatch(request, call_next)
        assert response.headers["X-Frame-Options"] == "DENY"

    @pytest.mark.asyncio
    async def test_calls_call_next(self):
        app = MagicMock()
        middleware = SecurityHeadersMiddleware(app)

        mock_response = MagicMock()
        mock_response.headers = {}
        call_next = AsyncMock(return_value=mock_response)
        request = MagicMock()

        await middleware.dispatch(request, call_next)
        call_next.assert_awaited_once_with(request)

    @pytest.mark.asyncio
    async def test_returns_response(self):
        app = MagicMock()
        middleware = SecurityHeadersMiddleware(app)

        mock_response = MagicMock()
        mock_response.headers = {}
        call_next = AsyncMock(return_value=mock_response)
        request = MagicMock()

        response = await middleware.dispatch(request, call_next)
        assert response is mock_response


# ---------------------------------------------------------------------------
# _check_stale_worktrees
# ---------------------------------------------------------------------------

class TestCheckStaleWorktrees:
    def _make_orchestrator(self, stale_entries):
        orchestrator = MagicMock()
        orchestrator.workflow_service.find_stale_worktrees = AsyncMock(
            return_value=stale_entries
        )
        return orchestrator

    @pytest.mark.asyncio
    async def test_no_stale_no_notifications(self):
        orchestrator = self._make_orchestrator([])
        with patch("src.web.routes.add_notification") as mock_add:
            await _check_stale_worktrees(orchestrator)
            mock_add.assert_not_called()
        orchestrator.workflow_service.find_stale_worktrees.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stale_entry_triggers_notification(self):
        stale = [{"item_id": "abc123def456", "title": "My Task", "reason": "orphaned"}]
        orchestrator = self._make_orchestrator(stale)

        with patch("src.web.routes.add_notification") as mock_add:
            await _check_stale_worktrees(orchestrator)
            mock_add.assert_called_once()
            call_args = mock_add.call_args
            assert call_args[0][0] == "warning"
            assert "My Task" in call_args[0][1]
            assert "orphaned" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_stale_entry_uses_item_id_prefix_when_no_title(self):
        item_id = "abcdef1234567890"
        stale = [{"item_id": item_id, "reason": "missing"}]
        orchestrator = self._make_orchestrator(stale)

        with patch("src.web.routes.add_notification") as mock_add:
            await _check_stale_worktrees(orchestrator)
            mock_add.assert_called_once()
            call_args = mock_add.call_args
            # title falls back to item_id[:8]
            assert item_id[:8] in call_args[0][1]

    @pytest.mark.asyncio
    async def test_stale_entry_action_contains_item_id(self):
        item_id = "abc123def456"
        stale = [{"item_id": item_id, "title": "T", "reason": "orphaned"}]
        orchestrator = self._make_orchestrator(stale)

        with patch("src.web.routes.add_notification") as mock_add:
            await _check_stale_worktrees(orchestrator)
            call_args = mock_add.call_args
            action = call_args[1]["action"]
            assert item_id in action["url"]
            assert action["method"] == "POST"
            assert action["label"] == "Clean up"

    @pytest.mark.asyncio
    async def test_stale_entry_source_contains_item_id(self):
        item_id = "abc123def456"
        stale = [{"item_id": item_id, "title": "T", "reason": "orphaned"}]
        orchestrator = self._make_orchestrator(stale)

        with patch("src.web.routes.add_notification") as mock_add:
            await _check_stale_worktrees(orchestrator)
            call_args = mock_add.call_args
            assert item_id in call_args[1]["source"]

    @pytest.mark.asyncio
    async def test_multiple_stale_entries_emit_multiple_notifications(self):
        stale = [
            {"item_id": "id1", "title": "Task 1", "reason": "orphaned"},
            {"item_id": "id2", "title": "Task 2", "reason": "missing"},
        ]
        orchestrator = self._make_orchestrator(stale)

        with patch("src.web.routes.add_notification") as mock_add:
            await _check_stale_worktrees(orchestrator)
            assert mock_add.call_count == 2

    @pytest.mark.asyncio
    async def test_exception_is_caught_and_logged(self):
        orchestrator = MagicMock()
        orchestrator.workflow_service.find_stale_worktrees = AsyncMock(
            side_effect=RuntimeError("DB gone")
        )

        # Should not raise
        with patch("src.web.app.logger") as mock_logger:
            await _check_stale_worktrees(orchestrator)
            mock_logger.warning.assert_called_once()
            assert "DB gone" in mock_logger.warning.call_args[0][0]

    @pytest.mark.asyncio
    async def test_exception_message_contains_stale_check_info(self):
        orchestrator = MagicMock()
        orchestrator.workflow_service.find_stale_worktrees = AsyncMock(
            side_effect=Exception("connection lost")
        )

        with patch("src.web.app.logger") as mock_logger:
            await _check_stale_worktrees(orchestrator)
            warning_msg = mock_logger.warning.call_args[0][0]
            assert "Stale worktree check failed" in warning_msg


# ---------------------------------------------------------------------------
# create_app
# ---------------------------------------------------------------------------

class TestCreateApp:
    def _make_paths(self, tmp_path):
        target = tmp_path / "target"
        target.mkdir()
        data = tmp_path / "data"
        data.mkdir()
        return target, data

    def test_app_title(self, tmp_path):
        target, data = self._make_paths(tmp_path)
        app = create_app(target, data)
        assert app.title == "Agents Dashboard"

    def test_state_target_project(self, tmp_path):
        target, data = self._make_paths(tmp_path)
        app = create_app(target, data)
        assert app.state.target_project == target

    def test_state_data_dir(self, tmp_path):
        target, data = self._make_paths(tmp_path)
        app = create_app(target, data)
        assert app.state.data_dir == data

    def test_db_path_uses_data_dir(self, tmp_path):
        target, data = self._make_paths(tmp_path)
        app = create_app(target, data)
        assert str(app.state.db.db_path) == str(data / "dashboard.db")

    def test_routes_included(self, tmp_path):
        target, data = self._make_paths(tmp_path)
        app = create_app(target, data)
        # Verify at least some routes are registered. Some route entries
        # (e.g. included routers in newer Starlette) have no `.path`, so guard.
        routes = [p for r in app.routes if (p := getattr(r, "path", None))]
        assert len(routes) > 0

    def test_static_mount_registered(self, tmp_path):
        target, data = self._make_paths(tmp_path)
        app = create_app(target, data)
        route_paths = [getattr(r, "path", None) for r in app.routes]
        assert "/static" in route_paths


# ---------------------------------------------------------------------------
# _audit_item_state_encodings
# ---------------------------------------------------------------------------

class TestAuditItemStateEncodings:
    @pytest.mark.asyncio
    async def test_clean_db_logs_nothing(self, tmp_path, caplog):
        db = Database(tmp_path / "clean.db")
        await db.initialize()
        async with db.connect() as conn:
            await conn.execute(
                "INSERT INTO items (id, title, description, column_name, status, position) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("a", "Ok item", "", "todo", None, 0),
            )
            await conn.execute(
                "INSERT INTO items (id, title, description, column_name, status, position) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("b", "Running item", "", "doing", "running", 0),
            )
            await conn.commit()
        with caplog.at_level("WARNING"):
            await _audit_item_state_encodings(db)
        # No warning should mention unrecognized encodings
        assert not any("unrecognized" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_bad_row_is_logged_not_raised(self, tmp_path, caplog):
        db = Database(tmp_path / "dirty.db")
        await db.initialize()
        async with db.connect() as conn:
            await conn.execute(
                "INSERT INTO items (id, title, description, column_name, status, position) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("bad", "Bad item", "", "doing", "totally_made_up", 0),
            )
            await conn.commit()
        with caplog.at_level("WARNING"):
            await _audit_item_state_encodings(db)
        warnings = [r.message for r in caplog.records if "unrecognized" in r.message]
        assert len(warnings) == 1
        assert "bad" in warnings[0]

    @pytest.mark.asyncio
    async def test_empty_db_is_silent(self, tmp_path, caplog):
        db = Database(tmp_path / "empty.db")
        await db.initialize()
        with caplog.at_level("WARNING"):
            await _audit_item_state_encodings(db)
        assert not any("unrecognized" in r.message for r in caplog.records)
