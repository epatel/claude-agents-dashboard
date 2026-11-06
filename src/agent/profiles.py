"""Provider profiles for agent sessions.

Single source of truth for how a run is routed to a provider backend and which
SDK options / dashboard features diverge per provider. Today there are three
profiles of the Claude Agent SDK runtime:

- "claude" — the default Anthropic backend.
- "ollama" — the same SDK redirected to Ollama's Anthropic-compatible endpoint
  via env vars. Lighter options so small local models aren't overwhelmed; see
  the field comments and AGENT_FILES/CARDS/OLLAMA_PROVIDER.md.
- "tiiny" — the same SDK redirected to a Tiiny device's Anthropic endpoint
  (http://anthropic.api.tiiny, served by the local TiinyOS PC Server). Shares
  the lean local-provider settings with Ollama; see
  AGENT_FILES/CARDS/TIINY_PROVIDER.md.

"ollama" and "tiiny" are both *local* profiles (`AgentProfile.local`): the
env that redirects the SDK is called the run's `local_env`.

Both `ClaudeAgentSession.start()` and `review_agent.run_auto_review()` consume these
profiles instead of forking on `is_ollama` locally.
"""

import logging
import os
import subprocess
import sys
from dataclasses import dataclass

from ..constants import DEFAULT_OLLAMA_BASE_URL, DEFAULT_TIINY_BASE_URL

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentProfile:
    name: str                         # "claude" | "ollama" | "tiiny"
    local: bool                       # ollama/tiiny: SDK redirected to a local provider
    permission_mode: str
    thinking: dict
    setting_sources: tuple[str, ...]
    env: dict[str, str]
    use_stderr_hook: bool             # local: log CLI stderr for diagnosis
    allow_chrome_extra_args: bool     # claude: pass --chrome when enabled
    # Feature gates (local providers disable heavy features that overwhelm small models)
    graphify: bool
    external_mcp: bool
    plugins: bool
    chrome: bool
    lifecycle_addendum: bool          # local: blunt "be decisive" prompt addendum
    inject_claude_md: bool            # local + per-provider "Load project CLAUDE.md" opt-in


def is_kimi_model(model: str | None) -> bool:
    """True when a model id routes to the Kimi Agent SDK runtime (kimi-*)."""
    return bool(model) and model.startswith("kimi-")


# Tiiny model ids are namespaced in the dashboard ("tiiny/default",
# "tiiny/<Model ID>") so they can't be mistaken for Ollama names; the prefix is
# stripped before the id reaches the SDK (see sdk_model_id).
TIINY_MODEL_PREFIX = "tiiny/"
# Keychain service name used when TIINY_API_KEY is not set (macOS). Same entry
# scripts/tiiny-smoke.sh reads.
TIINY_KEYCHAIN_SERVICE = "tiiny-api-key"
# Local NPU inference (and the first call after a model load) is slow.
TIINY_API_TIMEOUT_MS = "600000"


def is_tiiny_model(model: str | None) -> bool:
    """True when a model id routes to a Tiiny device (tiiny/*)."""
    return bool(model) and model.startswith(TIINY_MODEL_PREFIX)


def is_ollama_model(model: str | None) -> bool:
    """True when a model id routes to Ollama (anything not claude-*/kimi-*/tiiny/*)."""
    return bool(model) and not model.startswith(("claude-", "kimi-", TIINY_MODEL_PREFIX))


def sdk_model_id(model: str | None) -> str | None:
    """The model id to hand the SDK: Tiiny ids lose their dashboard prefix."""
    if is_tiiny_model(model):
        return model[len(TIINY_MODEL_PREFIX):] or "default"
    return model


def _clean_key(raw: str | None) -> str:
    """Strip whitespace and quotes (common copy-paste damage)."""
    return "".join(ch for ch in (raw or "") if not ch.isspace() and ch not in "\"'")


def get_tiiny_api_key() -> str:
    """The Tiiny API key: $TIINY_API_KEY, else the macOS Keychain, else "".

    The key is never stored in the dashboard DB and must never be logged.
    """
    key = _clean_key(os.environ.get("TIINY_API_KEY"))
    if key or sys.platform != "darwin":
        return key
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", TIINY_KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return _clean_key(out.stdout) if out.returncode == 0 else ""


def build_ollama_env(base_url: str) -> dict[str, str]:
    """Env vars that redirect the Claude Agent SDK to an Ollama endpoint."""
    return {
        "ANTHROPIC_AUTH_TOKEN": "ollama",
        "ANTHROPIC_API_KEY": "",
        "ANTHROPIC_BASE_URL": base_url,
    }


def resolve_ollama_env(config: dict, model: str | None) -> dict[str, str] | None:
    """Ollama env for a run, or None when the run stays on Anthropic.

    Ollama requires BOTH the config flag and a non-Claude model — Claude
    models must never be routed to Ollama.
    """
    if config.get("ollama_enabled") and is_ollama_model(model):
        return build_ollama_env(config.get("ollama_base_url", DEFAULT_OLLAMA_BASE_URL))
    return None


def build_tiiny_env(base_url: str, api_key: str, model_id: str) -> dict[str, str]:
    """Env vars that redirect the Claude Agent SDK to a Tiiny device.

    Every model tier maps to the one model the device serves, so the CLI's
    background (Haiku-tier) calls also stay on the device. The key goes in
    ANTHROPIC_AUTH_TOKEN, which the CLI sends as a Bearer token (what Tiiny
    accepts); this dict therefore holds a secret — never log it.
    """
    return {
        "ANTHROPIC_AUTH_TOKEN": api_key,
        "ANTHROPIC_API_KEY": "",
        "ANTHROPIC_BASE_URL": base_url,
        "ANTHROPIC_MODEL": model_id,
        "ANTHROPIC_DEFAULT_OPUS_MODEL": model_id,
        "ANTHROPIC_DEFAULT_SONNET_MODEL": model_id,
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": model_id,
        "ANTHROPIC_SMALL_FAST_MODEL": model_id,
        "API_TIMEOUT_MS": TIINY_API_TIMEOUT_MS,
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    }


def resolve_tiiny_env(config: dict, model: str | None) -> dict[str, str] | None:
    """Tiiny env for a run, or None when the run doesn't go to Tiiny.

    Requires BOTH the config flag and a tiiny/* model. A missing key still
    yields an env (with an empty token) so the run fails with a clear 401
    instead of silently going to Anthropic with a "tiiny/…" model id.
    """
    if not (config.get("tiiny_enabled") and is_tiiny_model(model)):
        return None
    api_key = get_tiiny_api_key()
    if not api_key:
        logger.warning(
            "Tiiny model selected but no API key found "
            f"(set TIINY_API_KEY or Keychain service '{TIINY_KEYCHAIN_SERVICE}')"
        )
    return build_tiiny_env(
        config.get("tiiny_base_url") or DEFAULT_TIINY_BASE_URL, api_key, sdk_model_id(model)
    )


def resolve_local_env(config: dict, model: str | None) -> dict[str, str] | None:
    """The local-provider env for a run (Tiiny or Ollama), or None for Anthropic."""
    if is_tiiny_model(model):
        return resolve_tiiny_env(config, model)
    return resolve_ollama_env(config, model)


def load_claude_md_for(config: dict, model: str | None) -> bool:
    """The provider-specific "Load project CLAUDE.md" opt-in for a run."""
    key = "tiiny_load_claude_md" if is_tiiny_model(model) else "ollama_load_claude_md"
    return bool(config.get(key, False))


def redact_env(env: dict[str, str] | None) -> dict[str, str]:
    """A copy of an env dict that is safe to log (secrets masked)."""
    return {
        k: ("***" if v and k in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY") and v != "ollama" else v)
        for k, v in (env or {}).items()
    }


_TIINY_UNREACHABLE_MARKERS = (
    "econnrefused", "connection refused", "enotfound", "getaddrinfo",
    "unable to connect", "fetch failed",
)


def tiiny_error_hint(status: int | None, text: str | None) -> str | None:
    """A user-facing explanation for a failed Tiiny call, or None."""
    if status == 401:
        return ("Tiiny: API key missing or wrong — set TIINY_API_KEY or the Keychain "
                f"entry '{TIINY_KEYCHAIN_SERVICE}' (copy it from TiinyOS → Settings → API Key)")
    if status == 404:
        return "Tiiny: wrong model ID, or no model loaded in TiinyOS"
    if status == 502:
        return "Tiiny: device reachable but its services are still starting — retry in a few minutes"
    lowered = (text or "").lower()
    if any(marker in lowered for marker in _TIINY_UNREACHABLE_MARKERS):
        return ("Tiiny not reachable — is TiinyOS running on this computer "
                "and connected to the device?")
    return None


def ollama_stderr_handler(line: str) -> None:
    """SDK stderr hook for Ollama runs (surfaces CLI-level failures)."""
    logger.info(f"[ollama-stderr] {line.rstrip()}")


def tiiny_stderr_handler(line: str) -> None:
    """SDK stderr hook for Tiiny runs (surfaces CLI-level failures)."""
    logger.info(f"[tiiny-stderr] {line.rstrip()}")


def resolve_profile(
    local_env: dict[str, str] | None,
    *,
    model: str | None = None,
    load_claude_md: bool = False,
) -> AgentProfile:
    """Profile for a session, keyed off the presence of a local-provider env.

    A local env selects the lean local profile; `model` names it ("tiiny" for
    tiiny/* ids, otherwise "ollama"). Both local providers share the settings
    below.

    Local-provider rationale (do not revert — see project-plan.md Decisions):
    - thinking disabled: Ollama returns unsigned thinking blocks that crash
      on replay ("Missing required field … 'signature'"). Kept off for Tiiny
      too: a small local model gains little from it and the risk is the same.
    - setting_sources=("local",): excludes `user` settings so global
      PreToolUse hooks (e.g. RTK) can't mangle plain command output, and
      skips project CLAUDE.md to keep context small (inject_claude_md is
      the explicit opt-in that adds it back via the system prompt).
    """
    if local_env:
        return AgentProfile(
            name="tiiny" if is_tiiny_model(model) else "ollama",
            local=True,
            permission_mode="bypassPermissions",
            thinking={"type": "disabled"},
            setting_sources=("local",),
            env=dict(local_env),
            use_stderr_hook=True,
            allow_chrome_extra_args=False,
            graphify=False,
            external_mcp=False,
            plugins=False,
            chrome=False,
            lifecycle_addendum=True,
            inject_claude_md=load_claude_md,
        )
    return AgentProfile(
        name="claude",
        local=False,
        permission_mode="acceptEdits",  # More targeted than bypassPermissions
        thinking={"type": "enabled", "budget_tokens": 32000},
        setting_sources=("project",),  # Load CLAUDE.md from target project
        env={},
        use_stderr_hook=False,
        allow_chrome_extra_args=True,
        graphify=True,
        external_mcp=True,
        plugins=True,
        chrome=True,
        lifecycle_addendum=False,
        inject_claude_md=False,
    )


def profile_options_kwargs(profile: AgentProfile) -> dict:
    """Divergent ClaudeAgentOptions kwargs for ClaudeAgentSession.start().

    Returns kwargs (not an options object) so ClaudeAgentOptions stays
    constructed at the call site — test patch targets depend on that.
    """
    kwargs = {
        "permission_mode": profile.permission_mode,
        "thinking": profile.thinking,
        "setting_sources": list(profile.setting_sources),
        "env": profile.env,
    }
    if profile.use_stderr_hook:
        kwargs["stderr"] = tiiny_stderr_handler if profile.name == "tiiny" else ollama_stderr_handler
    return kwargs
