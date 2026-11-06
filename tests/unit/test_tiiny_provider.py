"""Unit tests for the Tiiny provider (experimental local profile of the Claude runtime).

Covers routing (tiiny/* ids), API-key lookup, the env builder, the shared local
profile, error hints, the session / reviewer wiring, migration 033 and the
/api/tiiny/* routes. See AGENT_FILES/CARDS/TIINY_PROVIDER.md.
"""

import importlib.util
import logging
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest
import pytest_asyncio

from src.agent import profiles
from src.agent.profiles import (
    build_tiiny_env,
    get_tiiny_api_key,
    is_kimi_model,
    is_ollama_model,
    is_tiiny_model,
    load_claude_md_for,
    profile_options_kwargs,
    redact_env,
    resolve_local_env,
    resolve_profile,
    resolve_tiiny_env,
    sdk_model_id,
    tiiny_error_hint,
    tiiny_stderr_handler,
)
from src.constants import DEFAULT_TIINY_BASE_URL

TIINY_ENABLED = {"tiiny_enabled": True, "tiiny_base_url": "http://anthropic.api.tiiny"}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

class TestRouting:
    def test_tiiny_ids(self):
        assert is_tiiny_model("tiiny/default") is True
        assert is_tiiny_model("tiiny/Qwen3-30B-A3B") is True

    def test_non_tiiny_ids(self):
        for model in (None, "", "default", "claude-opus-5", "kimi-k2", "qwen3.5:9b"):
            assert is_tiiny_model(model) is False

    def test_tiiny_is_not_ollama_or_kimi(self):
        assert is_ollama_model("tiiny/default") is False
        assert is_kimi_model("tiiny/default") is False

    def test_sdk_model_id_strips_prefix(self):
        assert sdk_model_id("tiiny/default") == "default"
        assert sdk_model_id("tiiny/Qwen3-30B") == "Qwen3-30B"
        assert sdk_model_id("tiiny/") == "default"

    def test_sdk_model_id_leaves_other_ids(self):
        for model in ("claude-opus-5", "qwen3.5:9b", None):
            assert sdk_model_id(model) == model


# ---------------------------------------------------------------------------
# API key lookup
# ---------------------------------------------------------------------------

class TestApiKey:
    def test_env_var_wins_and_is_cleaned(self, monkeypatch):
        monkeypatch.setenv("TIINY_API_KEY", ' "sk-abc" \n')
        with patch("src.agent.profiles.subprocess.run") as run:
            assert get_tiiny_api_key() == "sk-abc"
        run.assert_not_called()

    def test_keychain_fallback_on_macos(self, monkeypatch):
        monkeypatch.delenv("TIINY_API_KEY", raising=False)
        monkeypatch.setattr(profiles.sys, "platform", "darwin")
        result = MagicMock(returncode=0, stdout="sk-keychain\n")
        with patch("src.agent.profiles.subprocess.run", return_value=result) as run:
            assert get_tiiny_api_key() == "sk-keychain"
        args = run.call_args.args[0]
        assert args[:2] == ["security", "find-generic-password"]
        assert "tiiny-api-key" in args

    def test_keychain_miss_returns_empty(self, monkeypatch):
        monkeypatch.delenv("TIINY_API_KEY", raising=False)
        monkeypatch.setattr(profiles.sys, "platform", "darwin")
        with patch("src.agent.profiles.subprocess.run", return_value=MagicMock(returncode=44, stdout="")):
            assert get_tiiny_api_key() == ""

    def test_keychain_error_returns_empty(self, monkeypatch):
        monkeypatch.delenv("TIINY_API_KEY", raising=False)
        monkeypatch.setattr(profiles.sys, "platform", "darwin")
        with patch("src.agent.profiles.subprocess.run", side_effect=subprocess.TimeoutExpired("security", 5)):
            assert get_tiiny_api_key() == ""

    def test_no_keychain_off_macos(self, monkeypatch):
        monkeypatch.delenv("TIINY_API_KEY", raising=False)
        monkeypatch.setattr(profiles.sys, "platform", "linux")
        with patch("src.agent.profiles.subprocess.run") as run:
            assert get_tiiny_api_key() == ""
        run.assert_not_called()


# ---------------------------------------------------------------------------
# Env
# ---------------------------------------------------------------------------

class TestTiinyEnv:
    def test_build_env_maps_every_tier_to_one_model(self):
        env = build_tiiny_env("http://anthropic.api.tiiny", "sk-x", "default")
        assert env["ANTHROPIC_BASE_URL"] == "http://anthropic.api.tiiny"
        assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-x"
        assert env["ANTHROPIC_API_KEY"] == ""
        for var in ("ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL",
                    "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL",
                    "ANTHROPIC_SMALL_FAST_MODEL"):
            assert env[var] == "default"
        assert int(env["API_TIMEOUT_MS"]) >= 120_000

    def test_disabled_returns_none(self):
        assert resolve_tiiny_env({"tiiny_enabled": False}, "tiiny/default") is None

    def test_non_tiiny_model_returns_none(self):
        assert resolve_tiiny_env(TIINY_ENABLED, "claude-opus-5") is None
        assert resolve_tiiny_env(TIINY_ENABLED, "qwen3.5:9b") is None

    def test_enabled_builds_env_with_stripped_model(self):
        with patch("src.agent.profiles.get_tiiny_api_key", return_value="sk-x"):
            env = resolve_tiiny_env(TIINY_ENABLED, "tiiny/Qwen3-30B")
        assert env == build_tiiny_env("http://anthropic.api.tiiny", "sk-x", "Qwen3-30B")

    def test_default_base_url_when_unset(self):
        with patch("src.agent.profiles.get_tiiny_api_key", return_value="sk-x"):
            env = resolve_tiiny_env({"tiiny_enabled": True}, "tiiny/default")
        assert env["ANTHROPIC_BASE_URL"] == DEFAULT_TIINY_BASE_URL

    def test_missing_key_still_routes_to_tiiny(self, caplog):
        """No key → env with an empty token (clear 401), never a silent Anthropic run."""
        with patch("src.agent.profiles.get_tiiny_api_key", return_value=""), \
             caplog.at_level(logging.WARNING, logger="src.agent.profiles"):
            env = resolve_tiiny_env(TIINY_ENABLED, "tiiny/default")
        assert env["ANTHROPIC_AUTH_TOKEN"] == ""
        assert env["ANTHROPIC_BASE_URL"] == "http://anthropic.api.tiiny"
        assert "no API key" in caplog.text

    def test_resolve_local_env_dispatch(self):
        config = {**TIINY_ENABLED, "ollama_enabled": True, "ollama_base_url": "http://box:11434"}
        with patch("src.agent.profiles.get_tiiny_api_key", return_value="sk-x"):
            assert resolve_local_env(config, "tiiny/default")["ANTHROPIC_BASE_URL"] == "http://anthropic.api.tiiny"
        assert resolve_local_env(config, "qwen3.5:9b")["ANTHROPIC_BASE_URL"] == "http://box:11434"
        assert resolve_local_env(config, "claude-opus-5") is None

    def test_tiiny_model_never_goes_to_ollama(self):
        config = {"ollama_enabled": True, "tiiny_enabled": False}
        assert resolve_local_env(config, "tiiny/default") is None

    def test_load_claude_md_is_per_provider(self):
        config = {"tiiny_load_claude_md": True, "ollama_load_claude_md": False}
        assert load_claude_md_for(config, "tiiny/default") is True
        assert load_claude_md_for(config, "qwen3.5:9b") is False

    def test_redact_env_masks_key(self):
        env = build_tiiny_env("http://anthropic.api.tiiny", "sk-secret", "default")
        safe = redact_env(env)
        assert "sk-secret" not in str(safe)
        assert safe["ANTHROPIC_BASE_URL"] == "http://anthropic.api.tiiny"
        assert redact_env(None) == {}


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

class TestTiinyProfile:
    def _env(self):
        return build_tiiny_env("http://anthropic.api.tiiny", "sk-x", "default")

    def test_profile_is_lean_local(self):
        p = resolve_profile(self._env(), model="tiiny/default")
        assert p.name == "tiiny"
        assert p.local is True
        assert p.thinking == {"type": "disabled"}
        assert p.setting_sources == ("local",)
        assert not (p.graphify or p.external_mcp or p.plugins or p.chrome)
        assert p.inject_claude_md is False

    def test_load_claude_md_opt_in(self):
        p = resolve_profile(self._env(), model="tiiny/default", load_claude_md=True)
        assert p.inject_claude_md is True

    def test_claude_and_ollama_profiles_keep_names(self):
        assert resolve_profile(None, model="tiiny/default").name == "claude"
        assert resolve_profile(None).local is False
        ollama = resolve_profile({"ANTHROPIC_BASE_URL": "http://localhost:11434"}, model="qwen3.5")
        assert ollama.name == "ollama" and ollama.local is True

    def test_kwargs_use_tiiny_stderr_handler(self):
        kwargs = profile_options_kwargs(resolve_profile(self._env(), model="tiiny/default"))
        assert kwargs["stderr"] is tiiny_stderr_handler
        assert kwargs["env"] == self._env()


class TestErrorHints:
    @pytest.mark.parametrize("status,needle", [
        (401, "API key"), (404, "model"), (502, "starting"),
    ])
    def test_status_hints(self, status, needle):
        assert needle in tiiny_error_hint(status, None)

    def test_unreachable_from_text(self):
        assert "not reachable" in tiiny_error_hint(None, "connect ECONNREFUSED 127.0.0.1:80")

    def test_unknown_error_has_no_hint(self):
        assert tiiny_error_hint(500, "boom") is None
        assert tiiny_error_hint(None, None) is None


# ---------------------------------------------------------------------------
# Session / reviewer wiring
# ---------------------------------------------------------------------------

class TestSessionWiring:
    @patch("src.agent.session.ClaudeSDKClient")
    @patch("src.agent.session.ClaudeAgentOptions")
    @pytest.mark.asyncio
    async def test_session_strips_prefix_and_redacts_log(self, mock_options_cls, mock_client_cls, tmp_path, caplog):
        from src.agent.session import ClaudeAgentSession

        mock_client_cls.return_value = AsyncMock()
        env = build_tiiny_env("http://anthropic.api.tiiny", "sk-secret", "default")
        session = ClaudeAgentSession(worktree_path=tmp_path, system_prompt="",
                                     model="tiiny/default", local_env=env)
        with caplog.at_level(logging.INFO, logger="src.agent.session"):
            try:
                await session.start("test")
            except Exception:
                pass

        kwargs = mock_options_cls.call_args.kwargs
        assert kwargs["model"] == "default"
        assert kwargs["env"] == env
        assert kwargs["thinking"] == {"type": "disabled"}
        assert "sk-secret" not in caplog.text
        assert "tiiny mode" in caplog.text

    @pytest.mark.asyncio
    async def test_reviewer_uses_tiiny_profile(self, tmp_path):
        from src.agent.review_agent import run_auto_review

        client = AsyncMock()

        async def _no_messages():
            return
            yield  # pragma: no cover

        client.receive_messages = MagicMock(side_effect=lambda: _no_messages())
        env = build_tiiny_env("http://anthropic.api.tiiny", "sk-x", "default")
        with patch("src.agent.review_agent.ClaudeSDKClient", MagicMock(return_value=client)), \
             patch("src.agent.review_agent.ClaudeAgentOptions") as options_cls:
            await run_auto_review(worktree_path=tmp_path, model="tiiny/default",
                                  item_title="t", item_description="d", diff="",
                                  last_message="", local_env=env)
        kwargs = options_cls.call_args.kwargs
        assert kwargs["model"] == "default"
        assert kwargs["env"] == env
        assert kwargs["thinking"] == {"type": "disabled"}

    @pytest.mark.asyncio
    async def test_session_service_routes_tiiny(self, tmp_path):
        from src.services.session_service import SessionService

        config = {**TIINY_ENABLED, "tiiny_load_claude_md": True}
        with patch("src.agent.profiles.get_tiiny_api_key", return_value="sk-x"), \
             patch("src.services.session_service.ClaudeAgentSession") as session_cls:
            await SessionService().create_session("item1", tmp_path, config, model="tiiny/default")
        kwargs = session_cls.call_args.kwargs
        assert kwargs["local_env"]["ANTHROPIC_BASE_URL"] == "http://anthropic.api.tiiny"
        assert kwargs["load_claude_md"] is True


# ---------------------------------------------------------------------------
# Migration 033
# ---------------------------------------------------------------------------

def _load_migration_033():
    versions = Path(__file__).resolve().parents[2] / "src" / "migrations" / "versions"
    spec = importlib.util.spec_from_file_location("migration_033", versions / "033_add_tiiny_config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.AddTiinyConfigMigration()


@pytest_asyncio.fixture
async def config_db():
    with tempfile.TemporaryDirectory() as tmp:
        conn = await aiosqlite.connect(str(Path(tmp) / "test.db"))
        conn.row_factory = aiosqlite.Row
        await conn.execute("CREATE TABLE agent_config (id INTEGER PRIMARY KEY, model TEXT)")
        await conn.execute("INSERT INTO agent_config (id, model) VALUES (1, 'x')")
        await conn.commit()
        yield conn
        await conn.close()


class TestMigration033:
    @pytest.mark.asyncio
    async def test_up_adds_columns_with_defaults(self, config_db):
        await _load_migration_033().up(config_db)
        cur = await config_db.execute(
            "SELECT tiiny_enabled, tiiny_base_url, tiiny_load_claude_md FROM agent_config WHERE id = 1"
        )
        row = await cur.fetchone()
        assert row["tiiny_enabled"] == 0
        assert row["tiiny_base_url"] == DEFAULT_TIINY_BASE_URL
        assert row["tiiny_load_claude_md"] == 0

    @pytest.mark.asyncio
    async def test_no_api_key_column(self, config_db):
        await _load_migration_033().up(config_db)
        cur = await config_db.execute("PRAGMA table_info(agent_config)")
        columns = {row["name"] for row in await cur.fetchall()}
        assert not any("key" in c for c in columns)
