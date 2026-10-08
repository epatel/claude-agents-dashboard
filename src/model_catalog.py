"""
Model catalog — the selectable model list, refreshed from a published feed.

The Claude and Kimi entries come from MODEL_LIST_URL; the bundled
`FALLBACK_CLAUDE_MODELS` / `KIMI_MODELS` lists are served until the first
successful fetch (and whenever the feed is unreachable, malformed, or missing
a provider). Ollama models are not in the catalog — they are discovered from
the user's own Ollama server (`/api/ollama/models`).
"""

import asyncio
import json
import logging
import re
import urllib.request

from .constants import (
    CLAUDE_1M_OPT_IN_MODELS,
    FALLBACK_CLAUDE_MODELS,
    KIMI_MODELS,
    MODEL_LIST_URL,
)

logger = logging.getLogger(__name__)

# Feed provider ids the dashboard has a runtime for, in dropdown order:
# provider -> (model id prefix, experimental, bundled fallback).
# Kimi ids in the feed are bare ("k3"); the Kimi CLI addresses them as
# "kimi-code/<id>" aliases, which is also what routes them to KimiAgentSession.
FEED_PROVIDERS = {
    "anthropic": ("", False, FALLBACK_CLAUDE_MODELS),
    "kimi-code-plan-global": ("kimi-code/", True, KIMI_MODELS),
}

REFRESH_INTERVAL_SECONDS = 6 * 60 * 60
FETCH_TIMEOUT_SECONDS = 10

# Model ids end up on a CLI command line and in rendered HTML/JS — accept only
# the characters real ids use.
_MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")

# Per-provider entries from the last successful fetch; empty until one succeeds.
_fetched_models: dict[str, list[tuple[str, str, bool]]] = {}


def parse_model_list(data: dict) -> dict[str, list[tuple[str, str, bool]]]:
    """Turn the feed payload into per-provider (model_id, display_name, experimental) entries.

    Keeps the feed's order (newest first), drops deprecated models, and adds
    the "[1m]" variant for the models that need the opt-in suffix. Providers
    with no usable models are left out.
    """
    by_provider: dict[str, list[tuple[str, str, bool]]] = {}
    seen: set[str] = set()
    for model in data.get("models", []):
        if not isinstance(model, dict) or model.get("provider") not in FEED_PROVIDERS:
            continue
        if model.get("status") == "deprecated":
            continue
        prefix, experimental, _ = FEED_PROVIDERS[model["provider"]]
        feed_id = model.get("id")
        if not isinstance(feed_id, str) or not _MODEL_ID_RE.match(feed_id):
            continue
        model_id = prefix + feed_id
        if model_id in seen:
            continue
        seen.add(model_id)
        name = model.get("name")
        if not isinstance(name, str) or not name.strip():
            name = feed_id
        entries = by_provider.setdefault(model["provider"], [])
        entries.append((model_id, name, experimental))
        if model_id in CLAUDE_1M_OPT_IN_MODELS:
            entries.append((f"{model_id}[1m]", f"{name} (1M)", experimental))
    return by_provider


def _fetch_model_list() -> dict:
    """Synchronous fetch — runs in a thread to avoid blocking the event loop."""
    req = urllib.request.Request(MODEL_LIST_URL, method="GET")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:
        return json.loads(resp.read().decode())


async def refresh() -> bool:
    """Fetch the feed and replace the cached entries. Never raises."""
    global _fetched_models
    try:
        data = await asyncio.to_thread(_fetch_model_list)
        entries = parse_model_list(data)
    except Exception as e:
        logger.warning(f"Model list fetch failed ({MODEL_LIST_URL}): {e} — keeping current list")
        return False
    if not entries:
        logger.warning(f"Model list from {MODEL_LIST_URL} had no usable models — keeping current list")
        return False
    _fetched_models = entries
    counts = ", ".join(f"{provider}: {len(models)}" for provider, models in entries.items())
    logger.info(f"Model list refreshed ({counts})")
    return True


async def periodic_refresh() -> None:
    """Refresh at startup, then every REFRESH_INTERVAL_SECONDS."""
    while True:
        await refresh()
        await asyncio.sleep(REFRESH_INTERVAL_SECONDS)


def get_available_models() -> list[tuple[str, str, bool]]:
    """The models to offer: each provider's fetched entries, or its bundled list."""
    models: list[tuple[str, str, bool]] = []
    for provider, (_, _, fallback) in FEED_PROVIDERS.items():
        models.extend(_fetched_models.get(provider) or fallback)
    return models
