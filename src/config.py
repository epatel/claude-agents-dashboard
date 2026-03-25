from pathlib import Path
from .constants import DEFAULT_MODEL

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

# Git operation timeouts (in seconds)
GIT_OPERATION_TIMEOUT = 300  # 5 minutes for most git operations
GIT_MERGE_TIMEOUT = 600      # 10 minutes for merge operations (can be slow on large repos)
HTTP_REQUEST_TIMEOUT = 660   # 11 minutes for HTTP requests (slightly longer than git merge timeout)

# WebSocket rate limiting
WEBSOCKET_MAX_CONNECTIONS_PER_IP = 5  # Max concurrent connections per IP
WEBSOCKET_RATE_LIMIT_WINDOW = 60      # Rate limit window in seconds
WEBSOCKET_MAX_CONNECTIONS_PER_WINDOW = 10  # Max connection attempts per window per IP

# Default agent config
DEFAULT_AGENT_CONFIG = {
    "system_prompt": "",
    "tools": [],
    "model": DEFAULT_MODEL,
    "project_context": "",
    "mcp_servers": {},
    "mcp_enabled": False,
    "plugins": [],
}
