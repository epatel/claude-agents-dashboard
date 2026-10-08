"""
Constants for the agents dashboard application.
"""

# Published model feed. src/model_catalog.py refreshes the Claude and Kimi
# entries from it; everything below is what the dashboard serves when it can't be reached.
MODEL_LIST_URL = "https://epatel.github.io/model-lists/models.json"

# Models that get an extra "<id>[1m]" entry. The "[1m]" suffix opts the spawned
# `claude` CLI into the optional 1M-token context window (no API beta header
# needed via the Agent SDK; standard pricing). Per Claude Code's model-config
# docs, the suffix applies only to Opus 4.6+ and Sonnet 4.6. Fable 5 and
# Sonnet 5 ALWAYS run at 1M on the API, so they need no suffix (and the CLI
# exposes no fable[1m]/sonnet-5[1m] variant). Opus 4.5 and Haiku 4.5 do not
# support 1M. The feed's context_window can't tell opt-in from always-on, so
# this stays a local list.
CLAUDE_1M_OPT_IN_MODELS = {
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
}

# Bundled Claude list, used until the feed has been fetched.
# Each entry: (model_id, display_name, experimental)
FALLBACK_CLAUDE_MODELS = [
    ("claude-haiku-5-5", "Claude Haiku 5.5", False),
    ("claude-sonnet-5-5", "Claude Sonnet 5.5", False),
    ("claude-opus-5-5", "Claude Opus 5.5", False),
    ("claude-fable-5-1", "Claude Fable 5.1", False),
    ("claude-fable-5", "Claude Fable 5", False),  # always 1M on the API
    ("claude-opus-5", "Claude Opus 5", False),
    ("claude-opus-5[1m]", "Claude Opus 5 (1M)", False),
    ("claude-sonnet-5", "Claude Sonnet 5", False),  # always 1M on the API
    ("claude-sonnet-4-6", "Claude Sonnet 4.6", False),
    ("claude-sonnet-4-6[1m]", "Claude Sonnet 4.6 (1M)", False),
    ("claude-opus-4-8", "Claude Opus 4.8", False),
    ("claude-opus-4-8[1m]", "Claude Opus 4.8 (1M)", False),
    ("claude-opus-4-7", "Claude Opus 4.7", False),
    ("claude-opus-4-7[1m]", "Claude Opus 4.7 (1M)", False),
    ("claude-opus-4-6", "Claude Opus 4.6", False),
    ("claude-opus-4-6[1m]", "Claude Opus 4.6 (1M)", False),
    ("claude-opus-4-5-20251101", "Claude Opus 4.5", False),
    ("claude-haiku-4-5-20251001", "Claude Haiku 4.5", False),
]

# Kimi models run through the Kimi Agent SDK (KimiAgentSession), not the
# Claude Agent SDK. Experimental — only offered when --experimental is on.
# Ids are kimi-code model ALIASES (see `kimi provider list` / config.toml):
# "kimi-code/" + the feed's `kimi-code-plan-global` id. Auth via `kimi login`
# (or KIMI_API_KEY). Bundled list, used until the feed has been fetched.
KIMI_MODELS = [
    ("kimi-code/kimi-for-coding", "kimi-for-coding", True),
    ("kimi-code/k3", "Kimi K3", True),
    ("kimi-code/k3-256k", "Kimi K3-256K", True),
    ("kimi-code/kimi-for-coding-highspeed", "Kimi For Coding HighSpeed", True),
]

# The full bundled list (what get_available_models() returns offline).
AVAILABLE_MODELS = [*FALLBACK_CLAUDE_MODELS, *KIMI_MODELS]

# Default model to use when none specified
DEFAULT_MODEL = "claude-opus-5"

# Default Ollama base URL
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"

# Auto-approve modes for items.
# Stored as INTEGER in the items.auto_approve column (legacy: 0/1 boolean).
#   0 (OFF)    — no auto-approve; the agent's work lands in Review for a human.
#   1 (REVIEW) — spawn a read-only review agent; auto-merge if it APPROVES.
#                If it requests changes, the comments go back to the original
#                agent (capped at 3 round-trips before falling back to manual).
#   2 (DIRECT) — auto-merge as soon as the agent finishes, with no review pass.
AUTO_APPROVE_OFF = 0
AUTO_APPROVE_REVIEW = 1
AUTO_APPROVE_DIRECT = 2
AUTO_APPROVE_MODES = {AUTO_APPROVE_OFF, AUTO_APPROVE_REVIEW, AUTO_APPROVE_DIRECT}

# Built-in Claude Code tools that can be opted-in via agent config.
# These require explicit allowlisting in permission_mode="acceptEdits".
OPTIONAL_BUILTIN_TOOLS = [
    {"name": "WebSearch", "label": "Web Search", "description": "Search the web for information"},
    {"name": "WebFetch", "label": "Web Fetch", "description": "Fetch content from URLs"},
]

# Preset epic color palette — keys map to CSS variables
# Each has light and dark variants defined in theme.css
EPIC_COLORS = [
    {"key": "red", "label": "Red", "light": "#dc2626", "dark": "#f87171"},
    {"key": "orange", "label": "Orange", "light": "#ea580c", "dark": "#fb923c"},
    {"key": "amber", "label": "Amber", "light": "#d97706", "dark": "#fbbf24"},
    {"key": "green", "label": "Green", "light": "#16a34a", "dark": "#4ade80"},
    {"key": "teal", "label": "Teal", "light": "#0d9488", "dark": "#2dd4a1"},
    {"key": "blue", "label": "Blue", "light": "#2563eb", "dark": "#60a5fa"},
    {"key": "purple", "label": "Purple", "light": "#7c3aed", "dark": "#a78bfa"},
    {"key": "pink", "label": "Pink", "light": "#db2777", "dark": "#f472b6"},
]