"""Provider profiles for agent sessions.

Single source of truth for how a run is routed to a provider backend and which
SDK options / dashboard features diverge per provider. Today there are two
profiles of the Claude Agent SDK runtime:

- "claude" — the default Anthropic backend.
- "ollama" — the same SDK redirected to Ollama's Anthropic-compatible endpoint
  via env vars. Lighter options so small local models aren't overwhelmed; see
  the field comments and AGENT_FILES/CARDS/OLLAMA_PROVIDER.md.

Both `ClaudeAgentSession.start()` and `review_agent.run_auto_review()` consume these
profiles instead of forking on `is_ollama` locally.
"""

import logging
from dataclasses import dataclass

from ..constants import DEFAULT_OLLAMA_BASE_URL

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentProfile:
    name: str                         # "claude" | "ollama"
    permission_mode: str
    thinking: dict
    setting_sources: tuple[str, ...]
    env: dict[str, str]
    use_stderr_hook: bool             # ollama: log CLI stderr for diagnosis
    allow_chrome_extra_args: bool     # claude: pass --chrome when enabled
    # Feature gates (Ollama disables heavy features that overwhelm small models)
    graphify: bool
    external_mcp: bool
    plugins: bool
    chrome: bool
    lifecycle_addendum: bool          # ollama: blunt "be decisive" prompt addendum
    inject_claude_md: bool            # ollama + ollama_load_claude_md opt-in


def is_kimi_model(model: str | None) -> bool:
    """True when a model id routes to the Kimi Agent SDK runtime (kimi-*)."""
    return bool(model) and model.startswith("kimi-")


def is_ollama_model(model: str | None) -> bool:
    """True when a model id routes to Ollama (anything not claude-*/kimi-*)."""
    return bool(model) and not model.startswith(("claude-", "kimi-"))


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


def ollama_stderr_handler(line: str) -> None:
    """SDK stderr hook for Ollama runs (surfaces CLI-level failures)."""
    logger.info(f"[ollama-stderr] {line.rstrip()}")


def resolve_profile(
    ollama_env: dict[str, str] | None,
    *,
    ollama_load_claude_md: bool = False,
) -> AgentProfile:
    """Profile for a session, keyed off the presence of an Ollama env.

    Ollama rationale (do not revert — see project-plan.md Decisions):
    - thinking disabled: Ollama returns unsigned thinking blocks that crash
      on replay ("Missing required field … 'signature'").
    - setting_sources=("local",): excludes `user` settings so global
      PreToolUse hooks (e.g. RTK) can't mangle plain command output, and
      skips project CLAUDE.md to keep context small (inject_claude_md is
      the explicit opt-in that adds it back via the system prompt).
    """
    if ollama_env:
        return AgentProfile(
            name="ollama",
            permission_mode="bypassPermissions",
            thinking={"type": "disabled"},
            setting_sources=("local",),
            env=dict(ollama_env),
            use_stderr_hook=True,
            allow_chrome_extra_args=False,
            graphify=False,
            external_mcp=False,
            plugins=False,
            chrome=False,
            lifecycle_addendum=True,
            inject_claude_md=ollama_load_claude_md,
        )
    return AgentProfile(
        name="claude",
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
        kwargs["stderr"] = ollama_stderr_handler
    return kwargs
