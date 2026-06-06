"""Tests for the graph_query MCP tool and its WorkflowService callback."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent.graph_query import create_graph_query_server
from src.agent.session import AgentSession
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
        s = AgentSession(worktree_path=tmp_path, system_prompt="",
                         on_graph_query=cb, graphify_enabled=True)
        assert s.graphify_enabled is True
        assert s.on_graph_query is cb

    def test_defaults_off(self, tmp_path):
        s = AgentSession(worktree_path=tmp_path, system_prompt="")
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
