"""HTTP endpoint tests for src/web/settings_routes.py."""

import pytest

from httpx import ASGITransport, AsyncClient

from tests.unit.route_fixtures import app_and_db, client  # noqa: F401  (pytest fixtures)
from tests.unit.route_fixtures import request


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

    @pytest.mark.asyncio
    async def test_graphify_fields_round_trip(self, client):
        # Defaults from migration 028
        data = (await client.get("/api/config")).json()
        assert data["graphify_enabled"] in (0, False)
        assert data["graphify_auto_refresh"] in (1, True)
        assert data["graphify_backend"] == "ast"
        # Persist new values
        payload = {
            "system_prompt": "", "model": "claude-opus-4-8",
            "graphify_enabled": True, "graphify_auto_refresh": False,
            "graphify_backend": "gemini",
        }
        resp = await client.put("/api/config", json=payload)
        assert resp.status_code == 200
        out = resp.json()
        assert out["graphify_enabled"] in (1, True)
        assert out["graphify_auto_refresh"] in (0, False)
        assert out["graphify_backend"] == "gemini"

    @pytest.mark.asyncio
    async def test_ollama_load_claude_md_round_trip(self, client):
        # Default from migration 030: off
        data = (await client.get("/api/config")).json()
        assert data["ollama_load_claude_md"] in (0, False)
        # Persist new value
        payload = {
            "system_prompt": "", "model": "claude-opus-4-8",
            "ollama_load_claude_md": True,
        }
        resp = await client.put("/api/config", json=payload)
        assert resp.status_code == 200
        assert resp.json()["ollama_load_claude_md"] in (1, True)


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


class TestGraphify:
    @pytest.mark.asyncio
    async def test_status(self, client):
        resp = await client.get("/api/graphify/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["installed_version"] == "0.8.33"
        assert data["graph"] == {"exists": False}

    @pytest.mark.asyncio
    async def test_build_starts(self, app_and_db):
        app, db = app_and_db
        resp = await request(app, "POST", "/api/graphify/build", json={"semantic": False})
        assert resp.status_code == 200
        assert resp.json() == {"started": True, "semantic": False}

    @pytest.mark.asyncio
    async def test_build_rejected_when_already_building(self, app_and_db):
        app, db = app_and_db
        app.state.orchestrator.graph_service._lock.locked.return_value = True
        resp = await request(app, "POST", "/api/graphify/build", json={"semantic": True})
        assert resp.status_code == 200
        assert resp.json() == {"started": False, "status": "already_building"}

    @pytest.mark.asyncio
    async def test_install(self, client):
        resp = await client.post("/api/graphify/install")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    @pytest.mark.asyncio
    async def test_query(self, app_and_db):
        app, db = app_and_db
        resp = await request(app, "GET", "/api/graphify/query", params={"q": "how does X work"})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "answer": "ans"}
        app.state.orchestrator.graph_service.query.assert_awaited_once_with("how does X work")

    @pytest.mark.asyncio
    async def test_query_blank_is_400(self, client):
        resp = await client.get("/api/graphify/query", params={"q": "   "})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_query_missing_param_is_422(self, client):
        resp = await client.get("/api/graphify/query")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Skills library endpoints
# ---------------------------------------------------------------------------


class TestSkills:
    @pytest.mark.asyncio
    async def test_list(self, client):
        resp = await client.get("/api/skills")
        assert resp.status_code == 200
        assert resp.json()["installed"][0]["name"] == "docx"

    @pytest.mark.asyncio
    async def test_browse(self, client):
        resp = await client.get("/api/skills/browse?source=anthropic")
        assert resp.status_code == 200
        assert resp.json()["skills"][0]["spec"].startswith("anthropics/skills/")

    @pytest.mark.asyncio
    async def test_install_auto_enables(self, app_and_db):
        app, db = app_and_db
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/skills/install", json={"spec": "anthropics/skills/skills/docx"})
            assert resp.status_code == 200 and resp.json()["ok"] is True
            assert resp.json()["enabled"] is True
            app.state.orchestrator.skills_service.install.assert_awaited_once_with("anthropics/skills/skills/docx")
            # the freshly installed skill is enabled for this project
            cfg = (await c.get("/api/config")).json()
        assert "docx" in (cfg.get("enabled_skills") or [])

    @pytest.mark.asyncio
    async def test_install_requires_spec(self, client):
        resp = await client.post("/api/skills/install", json={"spec": "  "})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_discover_lists_repo_skills(self, app_and_db):
        app, db = app_and_db
        resp = await request(app, "POST", "/api/skills/discover", json={"spec": "anthropics/skills"})
        assert resp.status_code == 200
        names = [s["name"] for s in resp.json()["skills"]]
        assert names == ["docx", "pdf"]
        app.state.orchestrator.skills_service.discover.assert_awaited_once_with("anthropics/skills")

    @pytest.mark.asyncio
    async def test_discover_requires_spec(self, client):
        resp = await client.post("/api/skills/discover", json={"spec": ""})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_enable_toggles_persist(self, client):
        # enable docx, then confirm it shows in the config + can be disabled
        r1 = await client.post("/api/skills/docx/enabled", json={"enabled": True})
        assert r1.status_code == 200 and "docx" in r1.json()["enabled"]
        cfg = (await client.get("/api/config")).json()
        assert "docx" in (cfg.get("enabled_skills") or [])
        r2 = await client.post("/api/skills/docx/enabled", json={"enabled": False})
        assert "docx" not in r2.json()["enabled"]

    @pytest.mark.asyncio
    async def test_remove_drops_from_enabled(self, client):
        await client.post("/api/skills/docx/enabled", json={"enabled": True})
        resp = await client.delete("/api/skills/docx")
        assert resp.status_code == 200 and resp.json()["ok"] is True
        cfg = (await client.get("/api/config")).json()
        assert "docx" not in (cfg.get("enabled_skills") or [])


# ---------------------------------------------------------------------------
# Tiiny (experimental local provider)
# ---------------------------------------------------------------------------
