"""
Constants for the agents dashboard application.
"""

# Available models - centralized to avoid duplication
AVAILABLE_MODELS = {
    "CLAUDE_SONNET_4": "claude-sonnet-4-20250514",
    "CLAUDE_SONNET_4_ADVISOR": "claude-sonnet-4-20250514+advisor",
    "CLAUDE_OPUS_3": "claude-3-opus-20240229",
    "CLAUDE_HAIKU_3": "claude-3-haiku-20240307",
}

# Default model to use when none specified
DEFAULT_MODEL = AVAILABLE_MODELS["CLAUDE_SONNET_4"]

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