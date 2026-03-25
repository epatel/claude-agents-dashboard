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

# File browser constants
FILE_BROWSER_EXCLUDED_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "agents-lab", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "dist", "build", ".egg-info", ".tox", ".next", ".nuxt",
    ".svelte-kit", "target", ".gradle", ".idea", ".vscode",
    ".superpowers",
}

FILE_BROWSER_EXCLUDED_FILES = {
    ".DS_Store", "Thumbs.db", "desktop.ini",
}

FILE_BROWSER_SECRET_PATTERNS = [
    ".env", ".env.*",
    "*.key", "*.pem", "*.p12", "*.pfx",
    "credentials.*", "*.secret", "*.secrets",
    "id_rsa", "id_rsa.*", "id_ed25519", "id_ed25519.*",
    "*.keystore", "*.jks",
]

FILE_BROWSER_MAX_TEXT_SIZE = 1_000_000  # 1MB
FILE_BROWSER_MAX_IMAGE_SIZE = 5_000_000  # 5MB
FILE_BROWSER_TREE_DEPTH = 2

FILE_BROWSER_LANGUAGE_MAP = {
    ".py": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".html": "html", ".htm": "html",
    ".css": "css",
    ".json": "json",
    ".yaml": "yaml", ".yml": "yaml",
    ".md": "markdown",
    ".sh": "bash", ".bash": "bash", ".zsh": "bash",
    ".sql": "sql",
    ".toml": "toml",
    ".xml": "xml",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".rb": "ruby",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".hpp": "cpp",
    ".dart": "dart",
}

FILE_BROWSER_IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico",
}

FILE_BROWSER_IMAGE_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
}
