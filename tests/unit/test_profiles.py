"""Unit tests for src/agent/profiles.py — provider routing and profiles."""

from src.agent.profiles import (
    AgentProfile,
    build_ollama_env,
    is_ollama_model,
    ollama_stderr_handler,
    profile_options_kwargs,
    resolve_ollama_env,
    resolve_profile,
)
from src.constants import DEFAULT_OLLAMA_BASE_URL


class TestIsOllamaModel:
    def test_none_is_not_ollama(self):
        assert is_ollama_model(None) is False

    def test_empty_string_is_not_ollama(self):
        assert is_ollama_model("") is False

    def test_claude_model_is_not_ollama(self):
        assert is_ollama_model("claude-opus-4-8") is False

    def test_local_model_is_ollama(self):
        assert is_ollama_model("qwen3.5:9b") is True


class TestBuildOllamaEnv:
    def test_exact_env_dict(self):
        assert build_ollama_env("http://localhost:11434") == {
            "ANTHROPIC_AUTH_TOKEN": "ollama",
            "ANTHROPIC_API_KEY": "",
            "ANTHROPIC_BASE_URL": "http://localhost:11434",
        }


class TestResolveOllamaEnv:
    def test_disabled_config_returns_none(self):
        assert resolve_ollama_env({"ollama_enabled": False}, "qwen3.5:9b") is None

    def test_claude_model_returns_none_even_when_enabled(self):
        assert resolve_ollama_env({"ollama_enabled": True}, "claude-opus-4-8") is None

    def test_enabled_with_ollama_model_returns_env(self):
        env = resolve_ollama_env(
            {"ollama_enabled": True, "ollama_base_url": "http://box:11434"}, "qwen3.5:9b"
        )
        assert env == build_ollama_env("http://box:11434")

    def test_default_base_url_when_unset(self):
        env = resolve_ollama_env({"ollama_enabled": True}, "qwen3.5:9b")
        assert env["ANTHROPIC_BASE_URL"] == DEFAULT_OLLAMA_BASE_URL


class TestResolveProfile:
    def test_claude_profile_values(self):
        p = resolve_profile(None)
        assert p.name == "claude"
        assert p.permission_mode == "acceptEdits"
        assert p.thinking == {"type": "enabled", "budget_tokens": 32000}
        assert p.setting_sources == ("project",)
        assert p.env == {}
        assert p.use_stderr_hook is False
        assert p.allow_chrome_extra_args is True
        assert p.graphify and p.external_mcp and p.plugins and p.chrome
        assert p.lifecycle_addendum is False
        assert p.inject_claude_md is False

    def test_ollama_profile_values(self):
        env = build_ollama_env(DEFAULT_OLLAMA_BASE_URL)
        p = resolve_profile(env)
        assert p.name == "ollama"
        assert p.permission_mode == "bypassPermissions"
        assert p.thinking == {"type": "disabled"}
        assert p.setting_sources == ("local",)
        assert p.env == env
        assert p.use_stderr_hook is True
        assert p.allow_chrome_extra_args is False
        assert not (p.graphify or p.external_mcp or p.plugins or p.chrome)
        assert p.lifecycle_addendum is True
        assert p.inject_claude_md is False

    def test_ollama_load_claude_md_opt_in(self):
        p = resolve_profile(build_ollama_env(DEFAULT_OLLAMA_BASE_URL), ollama_load_claude_md=True)
        assert p.inject_claude_md is True

    def test_load_claude_md_ignored_for_claude_profile(self):
        p = resolve_profile(None, ollama_load_claude_md=True)
        assert p.inject_claude_md is False

    def test_profile_is_frozen(self):
        import dataclasses
        import pytest

        with pytest.raises(dataclasses.FrozenInstanceError):
            resolve_profile(None).name = "other"

    def test_env_is_copied_not_shared(self):
        env = build_ollama_env(DEFAULT_OLLAMA_BASE_URL)
        p = resolve_profile(env)
        env["ANTHROPIC_BASE_URL"] = "mutated"
        assert p.env["ANTHROPIC_BASE_URL"] == DEFAULT_OLLAMA_BASE_URL


class TestProfileOptionsKwargs:
    def test_claude_kwargs_pin_current_literals(self):
        assert profile_options_kwargs(resolve_profile(None)) == {
            "permission_mode": "acceptEdits",
            "thinking": {"type": "enabled", "budget_tokens": 32000},
            "setting_sources": ["project"],
            "env": {},
        }

    def test_ollama_kwargs_pin_current_literals(self):
        env = build_ollama_env(DEFAULT_OLLAMA_BASE_URL)
        assert profile_options_kwargs(resolve_profile(env)) == {
            "permission_mode": "bypassPermissions",
            "thinking": {"type": "disabled"},
            "setting_sources": ["local"],
            "env": env,
            "stderr": ollama_stderr_handler,
        }
