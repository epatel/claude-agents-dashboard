"""
Constants for the agents dashboard application.
"""

# Available models - centralized to avoid duplication
AVAILABLE_MODELS = {
    "CLAUDE_SONNET_4": "claude-sonnet-4-20250514",
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