"""
Constants for the agents dashboard application.
"""

# Available models - centralized to avoid duplication
# Each entry: (model_id, display_name, experimental)
AVAILABLE_MODELS = [
    ("claude-sonnet-4-20250514", "Claude Sonnet 4", False),
    ("claude-sonnet-4-20250514+advisor", "Claude Sonnet 4 + Advisor", True),
    ("claude-opus-4-6", "Claude Opus 4.6", False),
    ("claude-haiku-4-5-20251001", "Claude Haiku 4.5", False),
]

# Default model to use when none specified
DEFAULT_MODEL = "claude-sonnet-4-20250514"

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