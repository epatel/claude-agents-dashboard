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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize database and orchestrator
    await app.state.db.initialize()
    app.state.orchestrator = AgentOrchestrator(
        target_project=app.state.target_project,
        data_dir=app.state.data_dir,
        db=app.state.db,
        ws_manager=app.state.ws_manager,
    )
    yield
    # Shutdown: stop all agents
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


def create_app(target_project: Path, data_dir: Path) -> FastAPI:
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

    # Mount static files
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Register routes
    from .routes import router
    app.include_router(router)

    from .file_routes import file_router
    app.include_router(file_router)

    return app
