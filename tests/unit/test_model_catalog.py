"""Unit tests for src/model_catalog.py — the feed-backed model list."""

from unittest.mock import patch

import pytest

from src import model_catalog
from src.constants import AVAILABLE_MODELS, DEFAULT_MODEL, KIMI_MODELS


def _model(model_id, name=None, provider="anthropic", status="active"):
    return {"provider": provider, "id": model_id, "name": name or model_id, "status": status}


@pytest.fixture(autouse=True)
def _reset_catalog():
    model_catalog._fetched_models = {}
    yield
    model_catalog._fetched_models = {}


class TestParseModelList:
    def test_keeps_feed_order_and_names(self):
        data = {"models": [_model("claude-b", "Claude B"), _model("claude-a", "Claude A")]}
        assert model_catalog.parse_model_list(data) == {"anthropic": [
            ("claude-b", "Claude B", False),
            ("claude-a", "Claude A", False),
        ]}

    def test_ignores_other_providers(self):
        data = {"models": [_model("gpt-9", provider="openai"), _model("claude-a")]}
        assert [m[0] for m in model_catalog.parse_model_list(data)["anthropic"]] == ["claude-a"]

    def test_drops_deprecated(self):
        data = {"models": [_model("claude-old", status="deprecated"), _model("claude-beta", status="beta")]}
        assert [m[0] for m in model_catalog.parse_model_list(data)["anthropic"]] == ["claude-beta"]

    def test_adds_1m_variant_for_opt_in_models(self):
        data = {"models": [_model("claude-opus-5", "Claude Opus 5"), _model("claude-sonnet-5", "Claude Sonnet 5")]}
        assert model_catalog.parse_model_list(data)["anthropic"] == [
            ("claude-opus-5", "Claude Opus 5", False),
            ("claude-opus-5[1m]", "Claude Opus 5 (1M)", False),
            ("claude-sonnet-5", "Claude Sonnet 5", False),
        ]

    def test_kimi_code_models_get_alias_prefix_and_experimental_flag(self):
        data = {"models": [
            _model("k3", "Kimi K3", provider="kimi-code-plan-global"),
            _model("kimi-k3", provider="moonshotai"),
        ]}
        assert model_catalog.parse_model_list(data) == {
            "kimi-code-plan-global": [("kimi-code/k3", "Kimi K3", True)],
        }

    def test_skips_malformed_entries(self):
        data = {"models": [
            "not-a-dict",
            {"provider": "anthropic"},
            _model("bad id'; alert(1)"),
            _model("claude-a"),
            _model("claude-a"),
        ]}
        assert [m[0] for m in model_catalog.parse_model_list(data)["anthropic"]] == ["claude-a"]

    def test_missing_name_falls_back_to_id(self):
        data = {"models": [{"provider": "anthropic", "id": "claude-a"}]}
        assert model_catalog.parse_model_list(data) == {"anthropic": [("claude-a", "claude-a", False)]}

    def test_empty_payload(self):
        assert model_catalog.parse_model_list({}) == {}


class TestGetAvailableModels:
    def test_bundled_list_before_any_fetch(self):
        assert model_catalog.get_available_models() == AVAILABLE_MODELS

    def test_bundled_list_offers_default_model(self):
        assert DEFAULT_MODEL in [m[0] for m in model_catalog.get_available_models()]

    async def test_refresh_replaces_every_provider_in_the_feed(self):
        feed = {"models": [_model("claude-new"), _model("k9", "Kimi K9", provider="kimi-code-plan-global")]}
        with patch.object(model_catalog, "_fetch_model_list", return_value=feed):
            assert await model_catalog.refresh() is True
        assert model_catalog.get_available_models() == [
            ("claude-new", "claude-new", False),
            ("kimi-code/k9", "Kimi K9", True),
        ]

    async def test_provider_missing_from_feed_keeps_its_bundled_list(self):
        with patch.object(model_catalog, "_fetch_model_list", return_value={"models": [_model("claude-new")]}):
            assert await model_catalog.refresh() is True
        assert model_catalog.get_available_models() == [("claude-new", "claude-new", False), *KIMI_MODELS]

    async def test_failed_fetch_keeps_bundled_list(self):
        with patch.object(model_catalog, "_fetch_model_list", side_effect=OSError("offline")):
            assert await model_catalog.refresh() is False
        assert model_catalog.get_available_models() == AVAILABLE_MODELS

    async def test_unusable_payload_keeps_previous_fetch(self):
        with patch.object(model_catalog, "_fetch_model_list", return_value={"models": [_model("claude-new")]}):
            await model_catalog.refresh()
        with patch.object(model_catalog, "_fetch_model_list", return_value={"models": []}):
            assert await model_catalog.refresh() is False
        assert model_catalog.get_available_models()[0][0] == "claude-new"
