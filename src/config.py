from pathlib import Path

# Directory where the dashboard source lives
DASHBOARD_DIR = Path(__file__).resolve().parent.parent

# Templates and static files
TEMPLATES_DIR = DASHBOARD_DIR / "src" / "templates"
STATIC_DIR = DASHBOARD_DIR / "src" / "static"

# Column definitions in display order
COLUMNS = [
    {"id": "todo", "label": "📝 Todo"},
    {"id": "doing", "label": "🚧 Doing"},
    {"id": "clarify", "label": "❓ Clarify"},
    {"id": "review", "label": "👀 Review"},
    {"id": "done", "label": "✅ Done"},
    {"id": "archive", "label": "📦 Archive"},
]

COLUMN_IDS = [c["id"] for c in COLUMNS]

# Data directory name created in target project
DATA_DIR_NAME = "agents-lab"

# Default starting port
DEFAULT_PORT = 8000
MAX_PORT_TRIES = 20

# Default agent config
DEFAULT_AGENT_CONFIG = {
    "system_prompt": "",
    "tools": [],
    "model": "claude-sonnet-4-20250514",
    "project_context": "",
    "mcp_servers": {},
    "mcp_enabled": False,
    "plugins": [],
}
