"""HTTP endpoint tests for src/web/shortcut_routes.py."""

import pytest

from tests.unit.route_fixtures import app_and_db, client  # noqa: F401  (pytest fixtures; app_and_db backs the others)


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
