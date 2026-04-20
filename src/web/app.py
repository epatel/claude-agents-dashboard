import asyncio
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

from ..config import TEMPLATES_DIR, STATIC_DIR, DEFAULT_HOST, DEFAULT_PORT, MAX_PORT_TRIES
from ..database import Database
from ..agent.orchestrator import AgentOrchestrator
from .websocket import ConnectionManager

logger = logging.getLogger(__name__)

STALE_WORKTREE_CHECK_INTERVAL = 300  # 5 minutes
MINIMUM_CLAUDE_CLI_VERSION = "2.1.111"


def _parse_claude_version(raw: str) -> tuple[int, ...] | None:
    """Extract a version tuple from output like "2.1.111 (Claude Code)"."""
    for token in raw.split():
        if "." in token and all(c.isdigit() or c == "." for c in token):
            try:
                return tuple(int(p) for p in token.split("."))
            except ValueError:
                continue
    return None


async def _check_claude_cli_version() -> None:
    """Warn if the installed Claude CLI is older than MINIMUM_CLAUDE_CLI_VERSION."""
    import shutil
    if not shutil.which("claude"):
        logger.warning("Claude CLI ('claude') not found on PATH — agents will fail to start.")
        return
    try:
        proc = await asyncio.create_subprocess_exec(
            "claude", "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
    except Exception as e:
        logger.warning(f"Could not run 'claude --version': {e}")
        return

    raw = stdout.decode(errors="replace").strip()
    current = _parse_claude_version(raw)
    minimum = _parse_claude_version(MINIMUM_CLAUDE_CLI_VERSION)
    if current is None or minimum is None:
        return
    if current < minimum:
        logger.warning(
            f"Claude CLI version {raw!r} is below required {MINIMUM_CLAUDE_CLI_VERSION}. "
            "Upgrade with: claude update"
        )


async def _check_stale_worktrees(orchestrator: AgentOrchestrator):
    """Check for stale worktrees and emit notifications."""
    from .routes import add_notification
    try:
        stale = await orchestrator.workflow_service.find_stale_worktrees()
        for entry in stale:
            item_id = entry["item_id"]
            title = entry.get("title", item_id[:8])
            reason = entry.get("reason", "stale")
            add_notification(
                "warning",
                f"Stale worktree for \"{title}\" ({reason})",
                source=f"stale-worktree:{item_id}",
                action={
                    "label": "Clean up",
                    "url": f"/api/cleanup/worktree/{item_id}",
                    "method": "POST",
                },
            )
    except Exception as e:
        logger.warning(f"Stale worktree check failed: {e}")


async def _periodic_stale_check(orchestrator: AgentOrchestrator):
    """Background task that periodically checks for stale worktrees."""
    while True:
        await asyncio.sleep(STALE_WORKTREE_CHECK_INTERVAL)
        await _check_stale_worktrees(orchestrator)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warn on stale Claude CLI before anything else
    await _check_claude_cli_version()

    # Startup: initialize database and orchestrator
    await app.state.db.initialize()
    app.state.orchestrator = AgentOrchestrator(
        target_project=app.state.target_project,
        data_dir=app.state.data_dir,
        db=app.state.db,
        ws_manager=app.state.ws_manager,
        repos=app.state.repos,
    )

    # Check for stale worktrees on startup
    await _check_stale_worktrees(app.state.orchestrator)

    # Start periodic stale worktree checker
    check_task = asyncio.create_task(_periodic_stale_check(app.state.orchestrator))

    # Start WebSocket heartbeat to detect and clean up dead connections
    app.state.ws_manager.start_heartbeat()

    yield

    # Shutdown: cancel periodic task, stop heartbeat, and stop all agents
    check_task.cancel()
    app.state.ws_manager.stop_heartbeat()
    await app.state.orchestrator.shutdown()


def _build_cors_origins() -> list[str]:
    """Build allowed CORS origins for localhost across the port range."""
    origins = []
    for port in range(DEFAULT_PORT, DEFAULT_PORT + MAX_PORT_TRIES):
        origins.append(f"http://{DEFAULT_HOST}:{port}")
        origins.append(f"http://localhost:{port}")
    return origins


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security response headers to all HTTP responses."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response


def create_app(target_project: Path, data_dir: Path, *, experimental: bool = False,
               repos: list[str] | None = None, ui_map: bool = False) -> FastAPI:
    """Create the FastAPI app.

    When `repos` is provided, the app runs in multi-repo mode: `target_project`
    is the parent folder and each item picks which subrepo under it to target.
    When `repos` is None, single-repo mode: `target_project` is the one repo.
    """
    app = FastAPI(title="Agents Dashboard", lifespan=lifespan)

    # Security headers (X-Content-Type-Options, X-Frame-Options)
    app.add_middleware(SecurityHeadersMiddleware)

    # Restrict cross-origin requests to localhost only.
    # Even though this runs locally, a malicious website in another tab
    # could otherwise make authenticated requests to the API.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_build_cors_origins(),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Store paths and shared objects on app state
    app.state.target_project = target_project
    app.state.data_dir = data_dir
    app.state.db = Database(data_dir / "dashboard.db")
    app.state.ws_manager = ConnectionManager()
    app.state.templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    # Stable hash-to-hue filter so the repo badge gets the same color on
    # server-rendered cards and JS-rendered cards (see Board.renderCard).
    def _repo_hue(name: str) -> int:
        h = 5381
        for ch in name or "":
            h = ((h * 33) + ord(ch)) & 0xFFFFFFFF
        return h % 360
    app.state.templates.env.filters["repo_hue"] = _repo_hue
    app.state.experimental = experimental
    app.state.ui_map = ui_map
    app.state.repos = repos or None

    # Mount static files
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Register routes
    from .routes import router
    app.include_router(router)

    from .file_routes import file_router
    app.include_router(file_router)

    return app
