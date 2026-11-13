"""HTTP endpoint tests for src/web/agent_routes.py."""

import pytest
from unittest.mock import AsyncMock

from tests.unit.route_fixtures import app_and_db, client_with_item  # noqa: F401  (pytest fixtures; app_and_db backs the others)


class TestPeekWorktrees:
    @pytest.mark.asyncio
    async def test_delegates_to_orchestrator(self, client_with_item):
        client, app = client_with_item
        app.state.orchestrator.peek_worktree = AsyncMock(return_value="peek text")
        resp = await client.get(
            "/api/items/item001/peek",
            params={"target_item_id": "other1", "path": "src/a.py"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"text": "peek text"}
        app.state.orchestrator.peek_worktree.assert_awaited_once_with(
            "item001", "other1", "src/a.py"
        )

    @pytest.mark.asyncio
    async def test_params_default_to_none(self, client_with_item):
        client, app = client_with_item
        app.state.orchestrator.peek_worktree = AsyncMock(return_value="summary")
        resp = await client.get("/api/items/item001/peek")
        assert resp.status_code == 200
        app.state.orchestrator.peek_worktree.assert_awaited_once_with("item001", None, None)


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
        # Pause now accepts an optional message — when no body is sent, the
        # route still forwards None so the orchestrator can keep a single
        # signature for both flows.
        app.state.orchestrator.pause_agent.assert_awaited_once_with("item001", None)

    @pytest.mark.asyncio
    async def test_pause_agent_with_message(self, client_with_item):
        client, app = client_with_item
        resp = await client.post(
            "/api/items/item001/pause",
            json={"message": "investigate a simpler approach"},
        )
        assert resp.status_code == 200
        app.state.orchestrator.pause_agent.assert_awaited_once_with(
            "item001", "investigate a simpler approach"
        )

    @pytest.mark.asyncio
    async def test_resume_agent(self, client_with_item):
        client, app = client_with_item
        resp = await client.post("/api/items/item001/resume")
        assert resp.status_code == 200
        # Resume now accepts an optional message — when no body is sent, the
        # route forwards None so the orchestrator can keep a single signature
        # for both flows (matches the pause endpoint).
        app.state.orchestrator.resume_agent.assert_awaited_once_with("item001", None)

    @pytest.mark.asyncio
    async def test_resume_agent_with_message(self, client_with_item):
        client, app = client_with_item
        resp = await client.post(
            "/api/items/item001/resume",
            json={"message": "try a different approach"},
        )
        assert resp.status_code == 200
        app.state.orchestrator.resume_agent.assert_awaited_once_with(
            "item001", "try a different approach"
        )

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


class TestStartCopyAgent:
    @pytest.mark.asyncio
    async def test_start_copy_agent(self, client_with_item):
        client, app = client_with_item
        resp = await client.post("/api/items/item001/start-copy")
        assert resp.status_code == 200
        app.state.orchestrator.start_copy_agent.assert_awaited_once_with("item001")

    @pytest.mark.asyncio
    async def test_start_copy_agent_returns_result(self, client_with_item):
        client, app = client_with_item
        resp = await client.post("/api/items/item001/start-copy")
        data = resp.json()
        assert data["status"] == "started"


# ---------------------------------------------------------------------------
# Create item with start_copy flag
# ---------------------------------------------------------------------------


class TestRetryMerge:
    @pytest.mark.asyncio
    async def test_retry_merge(self, client_with_item):
        client, app = client_with_item
        from src.domain.item_state import Event
        resp = await client.post("/api/items/item001/retry-merge")
        assert resp.status_code == 200
        # The route delegates the state transition to the repo; the repo
        # owns the from_columns / to_columns / write trio internally.
        app.state.orchestrator.item_repository.transition.assert_awaited_once_with(
            "item001", Event.RETRY_MERGE
        )
        app.state.orchestrator.approve_item.assert_awaited_once_with("item001")


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

    @pytest.mark.asyncio
    async def test_get_diff_unknown_item_is_404(self, client_with_item):
        client, app = client_with_item
        resp = await client.get("/api/items/nope/diff")
        assert resp.status_code == 404
        assert resp.json() == {"error": "Item not found"}


# ---------------------------------------------------------------------------
# Graphify endpoints
# ---------------------------------------------------------------------------
