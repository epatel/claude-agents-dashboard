from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..config import TEMPLATES_DIR, STATIC_DIR
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


def create_app(target_project: Path, data_dir: Path) -> FastAPI:
    app = FastAPI(title="Agents Dashboard", lifespan=lifespan)

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
