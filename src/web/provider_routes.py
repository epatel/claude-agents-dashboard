"""Local model providers (experimental): Ollama model discovery and the Tiiny
model list / connection test."""

import asyncio
import json
from typing import Any
from fastapi import APIRouter, Request
from ..constants import DEFAULT_OLLAMA_BASE_URL, DEFAULT_TIINY_BASE_URL

provider_router = APIRouter()


@provider_router.get("/api/ollama/models")
async def get_ollama_models(request: Request, force: bool = False):
    """Discover locally available Ollama models via the Ollama REST API."""
    base_url, enabled = await _ollama_settings(request.app.state.db)
    if not enabled and not force:
        return {"models": [], "error": None, "enabled": False}
    try:
        data = await asyncio.to_thread(_fetch_ollama_tags, base_url)
        models = [_ollama_model_entry(m) for m in data.get("models", [])]
        # Sort by name for stable ordering
        models.sort(key=lambda x: x["name"])
        return {"models": models, "error": None, "enabled": True}
    except Exception as e:
        return {"models": [], "error": _ollama_error_message(e), "enabled": True}


async def _ollama_settings(db) -> tuple[str, bool]:
    """(ollama_base_url, ollama_enabled) from agent_config; enabled when unreadable."""
    base_url, enabled = DEFAULT_OLLAMA_BASE_URL, True
    try:
        async with db.connect() as conn:
            cursor = await conn.execute("SELECT ollama_base_url, ollama_enabled FROM agent_config WHERE id = 1")
            row = await cursor.fetchone()
            if row:
                base_url = row["ollama_base_url"] or base_url
                enabled = bool(row["ollama_enabled"])
    except Exception:
        pass
    return base_url, enabled


def _fetch_ollama_tags(base_url: str) -> dict:
    """Blocking GET of Ollama's /api/tags — run it in a thread."""
    import urllib.request

    req = urllib.request.Request(f"{base_url}/api/tags", method="GET")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode())


def _ollama_model_entry(m: dict) -> dict:
    """One /api/tags model as a dashboard model entry, with a readable display name."""
    details = m.get("details", {})
    name = m.get("name", "")
    param_size = details.get("parameter_size", "")
    quant = details.get("quantization_level", "")
    display_parts = [name]
    if param_size:
        display_parts.append(f"({param_size})")
    if quant:
        display_parts.append(f"[{quant}]")
    return {
        "name": name,
        "display_name": " ".join(display_parts),
        "parameter_size": param_size,
        "quantization_level": quant,
        "family": details.get("family", ""),
        "size": m.get("size", 0),
    }


def _ollama_error_message(e: Exception) -> str:
    """User-facing message for a failed Ollama model listing."""
    import urllib.error

    if isinstance(e, urllib.error.URLError):
        reason = str(e.reason) if hasattr(e, 'reason') else str(e)
        if "Connection refused" in reason or "No connection" in reason:
            return "Cannot connect to Ollama. Is it running?"
        return f"Failed to reach Ollama: {reason}"
    if isinstance(e, TimeoutError):
        return "Ollama API timed out."
    return f"Failed to fetch models: {str(e)}"


# --- Tiiny (experimental local provider) ---

async def _tiiny_settings(request: Request) -> tuple[bool, str]:
    """(tiiny_enabled, tiiny_base_url) from agent_config."""
    enabled, base_url = False, DEFAULT_TIINY_BASE_URL
    try:
        async with request.app.state.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT tiiny_enabled, tiiny_base_url FROM agent_config WHERE id = 1"
            )
            row = await cursor.fetchone()
            if row:
                enabled = bool(row["tiiny_enabled"])
                base_url = row["tiiny_base_url"] or base_url
    except Exception:
        pass
    return enabled, base_url.rstrip("/")


def _tiiny_request(method: str, url: str, api_key: str, body: dict | None, timeout: float):
    """Blocking HTTP call to the Tiiny endpoint → (status, parsed JSON | text).

    status 0 means the endpoint could not be reached at all.
    """
    import urllib.error
    import urllib.request

    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("anthropic-version", "2023-06-01")
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")

    def _parse(raw: bytes):
        try:
            return json.loads(raw.decode() or "null")
        except ValueError:
            return raw.decode(errors="replace")[:500]

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, _parse(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, _parse(e.read())
    except (urllib.error.URLError, OSError) as e:
        return 0, str(getattr(e, "reason", e))


def _tiiny_status_message(status: int, detail: Any) -> str:
    from ..agent.profiles import tiiny_error_hint
    if status == 0:
        return tiiny_error_hint(None, "connection refused") or "Tiiny not reachable"
    return tiiny_error_hint(status, None) or f"Tiiny returned HTTP {status}: {str(detail)[:200]}"


@provider_router.get("/api/tiiny/models")
async def get_tiiny_models(request: Request, force: bool = False):
    """Models the Tiiny device offers, as dashboard ids (tiiny/<Model ID>).

    `tiiny/default` (whatever model is loaded in TiinyOS) is always offered,
    even when listing fails, so the provider stays usable.
    """
    from ..agent.profiles import TIINY_MODEL_PREFIX, get_tiiny_api_key

    enabled, base_url = await _tiiny_settings(request)
    if not enabled and not force:
        return {"models": [], "error": None, "enabled": False, "key_present": False}

    default = {"name": f"{TIINY_MODEL_PREFIX}default",
               "display_name": "Tiiny — loaded model (default)"}
    api_key = await asyncio.to_thread(get_tiiny_api_key)
    if not api_key:
        return {"models": [default], "enabled": True, "key_present": False,
                "error": "No API key: set TIINY_API_KEY or the Keychain entry 'tiiny-api-key'."}

    status, data = await asyncio.to_thread(
        _tiiny_request, "GET", f"{base_url}/v1/models", api_key, None, 10
    )
    models = [default]
    error = None
    if status == 200 and isinstance(data, dict):
        models += _tiiny_listed_models(data, TIINY_MODEL_PREFIX)
    elif status in (0, 401, 502):
        error = _tiiny_status_message(status, data)
    # Other statuses (e.g. 404: no model listing on this endpoint) are not an
    # error for the user — tiiny/default still works.
    return {"models": models, "error": error, "enabled": True, "key_present": True}


def _tiiny_listed_models(listing: dict, prefix: str) -> list[dict]:
    """Model entries for a /v1/models listing, skipping "default" (always offered)."""
    models = []
    for m in listing.get("data") or []:
        model_id = m.get("id") if isinstance(m, dict) else None
        if model_id and model_id != "default":
            models.append({
                "name": f"{prefix}{model_id}",
                "display_name": f"Tiiny — {m.get('display_name') or model_id}",
            })
    return models


@provider_router.post("/api/tiiny/test")
async def test_tiiny_connection(request: Request):
    """Send one short message ("Reply with the word OK") and report the reply."""
    from ..agent.profiles import get_tiiny_api_key, sdk_model_id

    body = await _json_body_or_empty(request)
    _, base_url = await _tiiny_settings(request)
    base_url = (body.get("base_url") or base_url).rstrip("/")
    model = sdk_model_id(body.get("model") or "tiiny/default")

    api_key = await asyncio.to_thread(get_tiiny_api_key)
    if not api_key:
        return {"ok": False, "status": None,
                "message": "No API key: set TIINY_API_KEY or the Keychain entry 'tiiny-api-key'."}

    status, data = await asyncio.to_thread(
        _tiiny_request, "POST", f"{base_url}/v1/messages", api_key,
        {"model": model, "max_tokens": 32,
         "messages": [{"role": "user", "content": "Reply with the word OK"}]},
        180,
    )
    if status != 200:
        return {"ok": False, "status": status or None, "message": _tiiny_status_message(status, data)}
    if not isinstance(data, dict):
        return {"ok": True, "status": 200, "model": None, "reply": "", "message": "Connected"}
    return {"ok": True, "status": 200, "model": data.get("model"),
            "reply": _message_text(data)[:200], "message": "Connected"}


async def _json_body_or_empty(request: Request) -> dict:
    """The request's JSON body, or {} when it has none (or it isn't JSON)."""
    try:
        return await request.json()
    except Exception:
        return {}


def _message_text(message: dict) -> str:
    """The joined text blocks of an Anthropic Messages API response, stripped."""
    return "".join(
        b.get("text", "") for b in message.get("content") or []
        if isinstance(b, dict) and b.get("type") == "text"
    ).strip()
