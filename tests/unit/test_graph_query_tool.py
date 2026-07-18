"""Tests for the graph_query MCP tool and its WorkflowService callback."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent.graph_query import create_graph_query_server
from src.agent.session import ClaudeAgentSession
from src.services.workflow_service import WorkflowService


def _make_workflow_service(graph_service=None):
    return WorkflowService(
        db_service=MagicMock(),
        git_service=MagicMock(),
        notification_service=MagicMock(),
        session_service=MagicMock(),
        graph_service=graph_service,
    )


class TestGraphQueryServer:
    def test_server_builds(self):
        srv = create_graph_query_server(AsyncMock(return_value="ans"))
        assert srv is not None


class TestAgentSessionWiring:
    def test_session_stores_graphify_fields(self, tmp_path):
        cb = AsyncMock(return_value="ans")
        s = ClaudeAgentSession(worktree_path=tmp_path, system_prompt="",
                         on_graph_query=cb, graphify_enabled=True)
        assert s.graphify_enabled is True
        assert s.on_graph_query is cb

    def test_defaults_off(self, tmp_path):
        s = ClaudeAgentSession(worktree_path=tmp_path, system_prompt="")
        assert s.graphify_enabled is False
        assert s.on_graph_query is None


class TestOnGraphQueryCallback:
    @pytest.mark.asyncio
    async def test_no_graph_service_returns_unavailable(self):
        ws = _make_workflow_service(graph_service=None)
        cb = ws._create_on_graph_query_callback()
        assert "not available" in (await cb("anything")).lower()

    @pytest.mark.asyncio
    async def test_ok_returns_answer(self):
        gs = MagicMock()
        gs.query = AsyncMock(return_value={"ok": True, "answer": "X calls Y"})
        ws = _make_workflow_service(graph_service=gs)
        cb = ws._create_on_graph_query_callback()
        assert await cb("what calls Y") == "X calls Y"
        gs.query.assert_awaited_once_with("what calls Y")

    @pytest.mark.asyncio
    async def test_failure_surfaces_error(self):
        gs = MagicMock()
        gs.query = AsyncMock(return_value={"ok": False, "error": "no graph"})
        ws = _make_workflow_service(graph_service=gs)
        cb = ws._create_on_graph_query_callback()
        out = await cb("q")
        assert "failed" in out.lower() and "no graph" in out


class TestAutoRefreshOnMerge:
    def _ws(self, graph_exists, auto_refresh):
        gs = MagicMock()
        gs.graph_json = MagicMock()
        gs.graph_json.exists.return_value = graph_exists
        gs.refresh = AsyncMock()
        ws = _make_workflow_service(graph_service=gs)
        ws.db.get_agent_config = AsyncMock(
            return_value={"graphify_auto_refresh": auto_refresh}
        )
        return ws, gs

    @pytest.mark.asyncio
    async def test_refreshes_when_enabled_and_graph_exists(self):
        ws, gs = self._ws(graph_exists=True, auto_refresh=True)
        await ws._maybe_refresh_graph_after_merge()
        await asyncio.sleep(0.01)  # let the fire-and-forget task run
        gs.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_refresh_when_disabled(self):
        ws, gs = self._ws(graph_exists=True, auto_refresh=False)
        await ws._maybe_refresh_graph_after_merge()
        await asyncio.sleep(0.01)
        gs.refresh.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_refresh_when_no_graph_yet(self):
        ws, gs = self._ws(graph_exists=False, auto_refresh=True)
        await ws._maybe_refresh_graph_after_merge()
        await asyncio.sleep(0.01)
        gs.refresh.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_graph_service_is_noop(self):
        ws = _make_workflow_service(graph_service=None)
        await ws._maybe_refresh_graph_after_merge()  # must not raise
