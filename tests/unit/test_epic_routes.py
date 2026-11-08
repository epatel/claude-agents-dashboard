"""HTTP endpoint tests for src/web/epic_routes.py."""

import pytest
from unittest.mock import AsyncMock

from tests.unit.route_fixtures import app_and_db, client, client_with_item  # noqa: F401  (pytest fixtures; app_and_db backs the others)


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
        from src.repositories.epic_repository import EpicNotFound
        client, app = client_with_item
        app.state.orchestrator.epic_repository.update = AsyncMock(
            side_effect=EpicNotFound("missing")
        )
        resp = await client.put("/api/epics/missing", json={"title": "X"})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_epic(self, client):
        resp = await client.delete("/api/epics/epic1")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @pytest.mark.asyncio
    async def test_delete_epic_not_found(self, client_with_item):
        from src.repositories.epic_repository import EpicNotFound
        client, app = client_with_item
        app.state.orchestrator.epic_repository.delete = AsyncMock(
            side_effect=EpicNotFound("missing")
        )
        resp = await client.delete("/api/epics/missing")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Shortcuts
# ---------------------------------------------------------------------------
