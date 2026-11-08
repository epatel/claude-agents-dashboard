"""Epics: list, colors, create, update, delete."""

from fastapi import APIRouter, Request, HTTPException
from ..constants import EPIC_COLORS
from ..repositories.epic_repository import EpicNotFound
from ..models import EpicCreate, EpicUpdate
from .stats_cache import _invalidate_stats_cache

epic_router = APIRouter()


# --- Epics ---

@epic_router.get("/api/epics")
async def get_epics(request: Request):
    """Get all epics with progress stats."""
    orchestrator = request.app.state.orchestrator
    epics = await orchestrator.epic_repository.list_all()
    # Progress aggregation still lives on db_service — it's a join across
    # items, not really an epic-CRUD concern. Could move to a dedicated
    # stats service later.
    progress = await orchestrator.db_service.get_epic_progress()
    for epic in epics:
        epic["progress"] = progress.get(epic["id"], {
            "todo": 0, "doing": 0, "questions": 0, "review": 0, "done": 0, "archive": 0, "total": 0
        })
    return epics


@epic_router.get("/api/epics/colors")
async def get_epic_colors():
    """Get the preset epic color palette."""
    return EPIC_COLORS


@epic_router.post("/api/epics")
async def create_epic(request: Request, body: EpicCreate):
    """Create a new epic."""
    orchestrator = request.app.state.orchestrator
    epic = await orchestrator.epic_repository.create(body.title, body.color)
    await orchestrator.notification_service.broadcast_epic_created(epic)
    _invalidate_stats_cache()
    return epic


@epic_router.put("/api/epics/{epic_id}")
async def update_epic(request: Request, epic_id: str, body: EpicUpdate):
    """Update an epic."""
    orchestrator = request.app.state.orchestrator
    fields = body.model_dump(exclude_unset=True)
    try:
        epic = await orchestrator.epic_repository.update(epic_id, **fields)
    except EpicNotFound:
        raise HTTPException(status_code=404, detail="Epic not found")
    await orchestrator.notification_service.broadcast_epic_updated(epic)
    return epic


@epic_router.delete("/api/epics/{epic_id}")
async def delete_epic(request: Request, epic_id: str):
    """Delete an epic (nullifies epic_id on related items)."""
    orchestrator = request.app.state.orchestrator
    try:
        await orchestrator.epic_repository.delete(epic_id)
    except EpicNotFound:
        raise HTTPException(status_code=404, detail="Epic not found")
    await orchestrator.notification_service.broadcast_epic_deleted(epic_id)
    _invalidate_stats_cache()
    return {"success": True}
