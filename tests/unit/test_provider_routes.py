"""HTTP endpoint tests for src/web/provider_routes.py."""

import pytest
from unittest.mock import patch

from tests.unit.route_fixtures import app_and_db, client  # noqa: F401  (pytest fixtures; app_and_db backs the others)


class TestTiinyRoutes:
    @pytest.mark.asyncio
    async def test_config_round_trip(self, client):
        data = (await client.get("/api/config")).json()
        assert data["tiiny_enabled"] in (0, False)
        assert data["tiiny_base_url"] == "http://anthropic.api.tiiny"
        payload = {"system_prompt": "", "model": "claude-opus-4-8",
                   "tiiny_enabled": True, "tiiny_base_url": "http://box.api.tiiny",
                   "tiiny_load_claude_md": True}
        out = (await client.put("/api/config", json=payload)).json()
        assert out["tiiny_enabled"] in (1, True)
        assert out["tiiny_base_url"] == "http://box.api.tiiny"
        assert out["tiiny_load_claude_md"] in (1, True)

    @pytest.mark.asyncio
    async def test_models_disabled(self, client):
        resp = await client.get("/api/tiiny/models")
        assert resp.json() == {"models": [], "error": None, "enabled": False, "key_present": False}

    @pytest.mark.asyncio
    async def test_models_without_key_still_offer_default(self, client):
        with patch("src.agent.profiles.get_tiiny_api_key", return_value=""):
            data = (await client.get("/api/tiiny/models?force=true")).json()
        assert [m["name"] for m in data["models"]] == ["tiiny/default"]
        assert data["key_present"] is False
        assert "TIINY_API_KEY" in data["error"]

    @pytest.mark.asyncio
    async def test_models_lists_device_models(self, client):
        listing = {"data": [{"id": "default"}, {"id": "Qwen3-30B", "display_name": "Qwen3 30B"}]}
        with patch("src.agent.profiles.get_tiiny_api_key", return_value="sk-x"), \
             patch("src.web.provider_routes._tiiny_request", return_value=(200, listing)) as req:
            data = (await client.get("/api/tiiny/models?force=true")).json()
        assert [m["name"] for m in data["models"]] == ["tiiny/default", "tiiny/Qwen3-30B"]
        assert data["error"] is None
        method, url, key = req.call_args.args[:3]
        assert (method, url, key) == ("GET", "http://anthropic.api.tiiny/v1/models", "sk-x")

    @pytest.mark.asyncio
    async def test_models_404_listing_is_not_an_error(self, client):
        with patch("src.agent.profiles.get_tiiny_api_key", return_value="sk-x"), \
             patch("src.web.provider_routes._tiiny_request", return_value=(404, "not found")):
            data = (await client.get("/api/tiiny/models?force=true")).json()
        assert [m["name"] for m in data["models"]] == ["tiiny/default"]
        assert data["error"] is None

    @pytest.mark.asyncio
    async def test_models_bad_key_reports_401(self, client):
        with patch("src.agent.profiles.get_tiiny_api_key", return_value="sk-bad"), \
             patch("src.web.provider_routes._tiiny_request", return_value=(401, {"type": "error"})):
            data = (await client.get("/api/tiiny/models?force=true")).json()
        assert "API key" in data["error"]

    @pytest.mark.asyncio
    async def test_connection_test_ok(self, client):
        reply = {"model": "Qwen3-30B", "content": [{"type": "text", "text": "OK"}]}
        with patch("src.agent.profiles.get_tiiny_api_key", return_value="sk-x"), \
             patch("src.web.provider_routes._tiiny_request", return_value=(200, reply)) as req:
            data = (await client.post("/api/tiiny/test", json={})).json()
        assert data["ok"] is True and data["reply"] == "OK"
        method, url, _key, body = req.call_args.args[:4]
        assert (method, url) == ("POST", "http://anthropic.api.tiiny/v1/messages")
        assert body["model"] == "default"

    @pytest.mark.asyncio
    async def test_connection_test_unreachable(self, client):
        with patch("src.agent.profiles.get_tiiny_api_key", return_value="sk-x"), \
             patch("src.web.provider_routes._tiiny_request", return_value=(0, "Connection refused")):
            data = (await client.post("/api/tiiny/test", json={})).json()
        assert data["ok"] is False
        assert "not reachable" in data["message"]

    @pytest.mark.asyncio
    async def test_connection_test_without_key(self, client):
        with patch("src.agent.profiles.get_tiiny_api_key", return_value=""), \
             patch("src.web.provider_routes._tiiny_request") as req:
            data = (await client.post("/api/tiiny/test", json={})).json()
        assert data["ok"] is False
        req.assert_not_called()
