import asyncio
import logging
from pathlib import Path
import time
from typing import Optional

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ..config import COLUMNS
from ..constants import DEFAULT_MODEL, DEFAULT_OLLAMA_BASE_URL, DEFAULT_TIINY_BASE_URL
from ..model_catalog import get_available_models
from ..models import AgentTodoCreate, ItemCreate, ItemUpdate, ItemMove, new_id
from ..git.operations import get_current_branch

from .route_helpers import _item_rows
from .stats_cache import _get_optimized_stats, _invalidate_stats_cache

router = APIRouter()


# --- Board page ---

@router.get("/", response_class=HTMLResponse)
async def board_page(request: Request):
    db = request.app.state.db
    db_service = request.app.state.orchestrator.db_service
    async with db.connect() as conn:
        cursor = await conn.execute(
            "SELECT items.*, epics.title as epic_title, epics.color as epic_color,"
            " COALESCE(wl.cnt, 0) AS log_count"
            " FROM items"
            " LEFT JOIN epics ON items.epic_id = epics.id"
            " LEFT JOIN (SELECT item_id, COUNT(*) AS cnt FROM work_log GROUP BY item_id) wl"
            " ON items.id = wl.item_id"
            " ORDER BY items.column_name, items.position"
        )
        rows = await cursor.fetchall()
        items = [dict(row) for row in rows]

    # Get blocked status for todo items
    blocked_status = await db_service.get_all_blocked_status()

    # Annotate items with blocked info for template rendering
    for item in items:
        blockers = blocked_status.get(item["id"], [])
        item["is_blocked"] = len(blockers) > 0
        item["blocking_items"] = blockers

    # Get current git branch name (single-repo mode only — multi-mode has a
    # different branch per subrepo, so leave it blank and let the frontend
    # decide how to surface per-repo info).
    repos = request.app.state.repos
    if repos:
        current_branch = ""
    else:
        current_branch = await get_current_branch(request.app.state.target_project)

    return request.app.state.templates.TemplateResponse(
        request=request,
        name="board.html",
        context={
            "columns": COLUMNS,
            "items": items,
            "project_name": request.app.state.target_project.name,
            "current_branch": current_branch,
            "experimental": getattr(request.app.state, "experimental", False),
            "ui_map": getattr(request.app.state, "ui_map", False),
            "available_models": get_available_models(),
            "default_model": DEFAULT_MODEL,
            "default_ollama_url": DEFAULT_OLLAMA_BASE_URL,
            "default_tiiny_url": DEFAULT_TIINY_BASE_URL,
            "workspace_repos": sorted(repos) if repos else [],
            "workspace_mode": "multi" if repos else "single",
        },
    )


# --- Items CRUD ---

@router.get("/api/items")
async def list_items(request: Request):
    db = request.app.state.db
    async with db.connect() as conn:
        cursor = await conn.execute("SELECT * FROM items ORDER BY column_name, position")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


@router.get("/api/search/worklog")
async def search_worklog(request: Request, q: str = ""):
    """Search work log entries and return matching item IDs with snippets."""
    if not q or len(q) < 2:
        return []
    db = request.app.state.db
    async with db.connect() as conn:
        cursor = await conn.execute(
            "SELECT DISTINCT w.item_id, w.content, i.title, i.column_name "
            "FROM work_log w JOIN items i ON w.item_id = i.id "
            "WHERE w.content LIKE ? ORDER BY w.timestamp DESC LIMIT 50",
            (f"%{q}%",),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


def _validated_repo(known_repos, repo: Optional[str]) -> Optional[str]:
    """The item's repo, checked against the workspace's known repos.

    In multi-repo mode a repo is required and must be known (HTTP 400
    otherwise); a single-repo workspace silently drops any repo it is sent.
    """
    if not known_repos:
        return None
    repo = repo or None
    if not repo:
        raise HTTPException(
            status_code=400,
            detail="repo is required in multi-repo mode",
        )
    if repo not in known_repos:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown repo '{repo}'. Known: {sorted(known_repos)}",
        )
    return repo


@router.post("/api/items")
async def create_item(request: Request, body: ItemCreate):
    db = request.app.state.db
    item_id = new_id()
    repo = _validated_repo(request.app.state.repos, body.repo)

    async with db.connect() as conn:
        # Get next position in todo
        cursor = await conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM items WHERE column_name = 'todo'"
        )
        row = await cursor.fetchone()
        position = row[0]

        if body.epic_id:
            cursor = await conn.execute("SELECT id FROM epics WHERE id = ?", (body.epic_id,))
            if not await cursor.fetchone():
                raise HTTPException(status_code=400, detail="Epic not found")

        await conn.execute(
            "INSERT INTO items (id, title, description, column_name, position, model, epic_id, auto_start, start_copy, auto_approve, use_chrome, repo) VALUES (?, ?, ?, 'todo', ?, ?, ?, ?, ?, ?, ?, ?)",
            (item_id, body.title, body.description, position, body.model, body.epic_id, int(body.auto_start), int(body.start_copy), int(body.auto_approve), int(body.use_chrome), repo),
        )
        await conn.commit()

        cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
        item = dict(await cursor.fetchone())

    await request.app.state.ws_manager.broadcast("item_created", item)
    _invalidate_stats_cache()  # New item affects stats
    return item


@router.post("/api/items/{item_id}/agent-todos")
async def create_agent_todo(request: Request, item_id: str, body: AgentTodoCreate):
    """Create a todo on behalf of a running agent (out-of-process tool proxies).

    Runs through the same workflow callback as the Claude agents' create_todo
    MCP tool — dependency wiring (`requires`), autostart with the
    unmerged-creator auto-anchor, and board broadcasts included.
    """
    db = request.app.state.db
    async with db.connect() as conn:
        cursor = await conn.execute("SELECT id FROM items WHERE id = ?", (item_id,))
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="Creator item not found")

    orchestrator = request.app.state.orchestrator
    item = await orchestrator.create_agent_todo(
        item_id,
        title=body.title,
        description=body.description,
        epic_id=body.epic_id,
        requires=body.requires,
        autostart=body.autostart,
        auto_approve=body.auto_approve,
        use_chrome=body.use_chrome,
    )
    _invalidate_stats_cache()
    return item


@router.get("/api/workspace")
async def get_workspace(request: Request):
    """Return the workspace mode and repo list for the frontend."""
    repos = request.app.state.repos
    return {
        "mode": "multi" if repos else "single",
        "repos": sorted(repos) if repos else [],
        "root": str(request.app.state.target_project),
    }


@router.patch("/api/items/{item_id}")
async def update_item(request: Request, item_id: str, body: ItemUpdate):
    db = request.app.state.db
    async with db.connect() as conn:
        updates = []
        values = []
        for field, value in body.model_dump(exclude_unset=True).items():
            updates.append(f"{field} = ?")
            values.append(value)

        if not updates:
            cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
            return dict(await cursor.fetchone())

        updates.append("updated_at = datetime('now')")
        values.append(item_id)

        await conn.execute(
            f"UPDATE items SET {', '.join(updates)} WHERE id = ?",
            values,
        )
        await conn.commit()

        cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
        item = dict(await cursor.fetchone())

    await request.app.state.ws_manager.broadcast("item_updated", item)
    return item


@router.delete("/api/items/{item_id}")
async def delete_item(request: Request, item_id: str):
    orchestrator = request.app.state.orchestrator
    result = await orchestrator.delete_item(item_id)
    _invalidate_stats_cache()  # Item deletion affects stats
    return result


class ArchiveByDateRequest(BaseModel):
    date: str  # YYYY-MM-DD


@router.post("/api/items/archive-by-date")
async def archive_items_by_date(request: Request, body: ArchiveByDateRequest):
    """Archive all done items from a specific date."""
    return await _archive_done_items(
        request, "DATE(COALESCE(done_at, updated_at)) = ?", (body.date,)
    )


async def _archive_done_items(request: Request, condition: str, params: tuple) -> dict:
    """Move every done item matching ``condition`` to the archive and broadcast each move.

    ``condition`` is a fixed SQL fragment from this module (never user input);
    values go in ``params``.
    """
    db = request.app.state.db
    async with db.connect() as conn:
        cursor = await conn.execute(
            f"SELECT id FROM items WHERE column_name = 'done' AND {condition}", params,
        )
        item_ids = [row[0] for row in await cursor.fetchall()]
        if not item_ids:
            return {"archived": 0}

        placeholders = ",".join("?" for _ in item_ids)
        await conn.execute(
            f"UPDATE items SET column_name = 'archive', updated_at = datetime('now') WHERE id IN ({placeholders})",
            item_ids,
        )
        await conn.commit()

    # Broadcast move for each archived item so the UI updates
    async with db.connect() as conn:
        for item_id in item_ids:
            cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
            item = dict(await cursor.fetchone())
            await request.app.state.ws_manager.broadcast("item_moved", item)

    _invalidate_stats_cache()
    return {"archived": len(item_ids)}


class ArchiveByEpicRequest(BaseModel):
    epic_id: str


@router.post("/api/items/archive-by-epic")
async def archive_items_by_epic(request: Request, body: ArchiveByEpicRequest):
    """Archive all done items belonging to an epic.

    Intended to be invoked from the sidebar's epic card when the epic has
    reached 100% completion (all items done). Items in 'todo', 'doing',
    'questions', or 'review' are left untouched so an in-flight task is never
    yanked away mid-flight.
    """
    return await _archive_done_items(request, "epic_id = ?", (body.epic_id,))


class DeleteByDateRequest(BaseModel):
    date: str  # YYYY-MM-DD
    column_name: str  # e.g. 'archive'


@router.post("/api/items/delete-by-date")
async def delete_items_by_date(request: Request, body: DeleteByDateRequest):
    """Delete all items from a specific column and date."""
    db = request.app.state.db
    orchestrator = request.app.state.orchestrator
    async with db.connect() as conn:
        cursor = await conn.execute(
            "SELECT id FROM items WHERE column_name = ? AND DATE(COALESCE(done_at, updated_at)) = ?",
            (body.column_name, body.date),
        )
        rows = await cursor.fetchall()
        item_ids = [row[0] for row in rows]

    if not item_ids:
        return {"deleted": 0}

    for item_id in item_ids:
        await orchestrator.delete_item(item_id)

    _invalidate_stats_cache()
    return {"deleted": len(item_ids)}


class DeleteByEpicRequest(BaseModel):
    epic_id: str


@router.post("/api/items/delete-by-epic")
async def delete_items_by_epic(request: Request, body: DeleteByEpicRequest):
    """Delete all todo items in an epic. If no items remain, delete the epic too."""
    db = request.app.state.db
    orchestrator = request.app.state.orchestrator
    async with db.connect() as conn:
        cursor = await conn.execute(
            "SELECT id FROM items WHERE epic_id = ? AND column_name = 'todo'",
            (body.epic_id,),
        )
        todo_ids = [row[0] for row in await cursor.fetchall()]

        # Check if there are active (non-todo, non-archive) items remaining
        cursor2 = await conn.execute(
            "SELECT COUNT(*) FROM items WHERE epic_id = ? AND column_name NOT IN ('todo', 'archive')",
            (body.epic_id,),
        )
        remaining = (await cursor2.fetchone())[0]

    for item_id in todo_ids:
        await orchestrator.delete_item(item_id)

    # If no items remain in other columns, delete the epic
    deleted_epic = False
    if remaining == 0:
        epic_repo = request.app.state.orchestrator.epic_repository
        ns = request.app.state.orchestrator.notification_service
        await epic_repo.delete(body.epic_id)
        await ns.broadcast_epic_deleted(body.epic_id)
        deleted_epic = True

    _invalidate_stats_cache()
    return {"deleted": len(todo_ids), "epic_deleted": deleted_epic}


@router.post("/api/items/{item_id}/move")
async def move_item(request: Request, item_id: str, body: ItemMove):
    orchestrator = request.app.state.orchestrator
    terminal = body.column_name in ("done", "archive")

    # Clean up agent resources when moving to done or archive (external state
    # — sessions and git worktrees — kept in the route since the repo only
    # owns the data row).
    if terminal:
        await _release_agent_resources(orchestrator, item_id)

    # Make room in target column, then perform the move via the repo. The
    # repo normalizes status on cross-column moves, preserves it on
    # within-column reorders, clears worktree_path on done/archive, and
    # carries done_at forward to archive.
    await orchestrator.item_repository.shift_positions(
        body.column_name, body.position, item_id
    )
    item = await orchestrator.item_repository.move_to_column(
        item_id, body.column_name, body.position
    )

    await request.app.state.ws_manager.broadcast("item_moved", item)
    _invalidate_stats_cache()  # Item status change affects stats

    if terminal:
        await _unblock_dependents(request, orchestrator, item_id)
    return item


async def _release_agent_resources(orchestrator, item_id: str) -> None:
    """End the item's session and remove its worktree and branch, if any."""
    old_item = await orchestrator.item_repository.get(item_id)
    await orchestrator.session_service.cleanup_session(item_id)
    if not old_item:
        return
    if old_item.get("worktree_path") and old_item.get("branch_name"):
        await orchestrator.git_service.cleanup_worktree_and_branch(
            Path(old_item["worktree_path"]), old_item["branch_name"])


async def _unblock_dependents(request: Request, orchestrator, item_id: str) -> None:
    """After a move to done/archive: refresh blocked badges and auto-start dependents.

    The item's dependents may become unblocked. Refresh the UI's blocked-state
    badges *and* fire the auto-start hook so any dependent with auto_start=true
    actually launches — without this the auto-start chain only ran for items
    reaching done via the merge path, missing direct drag-to-done/archive moves.
    """
    db_service = orchestrator.db_service
    dependent_ids = await db_service.get_dependent_items(item_id)
    if dependent_ids:
        blocked_status = await db_service.get_all_blocked_status()
        await request.app.state.ws_manager.broadcast("blocked_status_changed", {
            "blocked": blocked_status,
        })
    await orchestrator.workflow_service.notify_and_auto_start_dependents(item_id)


# --- Dependencies ---

class SetDependenciesBody(BaseModel):
    required_item_ids: list[str]


@router.get("/api/items/{item_id}/dependencies")
async def get_item_dependencies(request: Request, item_id: str):
    """Get list of items this item depends on."""
    db_service = request.app.state.orchestrator.db_service
    return await db_service.get_item_dependencies(item_id)


@router.put("/api/items/{item_id}/dependencies")
async def set_item_dependencies(request: Request, item_id: str, body: SetDependenciesBody):
    """Replace the full list of dependencies for an item."""
    db_service = request.app.state.orchestrator.db_service
    try:
        deps = await db_service.set_item_dependencies(item_id, body.required_item_ids)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # Broadcast so the frontend can re-evaluate blocked states
    item = await db_service.get_item(item_id)
    if item:
        await request.app.state.ws_manager.broadcast("dependencies_changed", {
            "item_id": item_id,
            "dependencies": deps,
        })
        # Also broadcast full blocked status so all cards update
        blocked_status = await db_service.get_all_blocked_status()
        await request.app.state.ws_manager.broadcast("blocked_status_changed", {
            "blocked": blocked_status,
        })
    return deps


@router.get("/api/items/{item_id}/is-blocked")
async def is_item_blocked(request: Request, item_id: str):
    """Check if this item is blocked by any unfinished dependency."""
    db_service = request.app.state.orchestrator.db_service
    blocked = await db_service.is_item_blocked(item_id)
    blocking_items = await db_service.get_blocking_items(item_id) if blocked else []
    return {"blocked": blocked, "blocking_items": blocking_items}


@router.get("/api/items/blocked-status")
async def get_all_blocked_status(request: Request):
    """Get blocked status for all todo items with unresolved dependencies.

    Returns a dict mapping item_id -> list of blocking items.
    Only includes items that ARE blocked.
    """
    db_service = request.app.state.orchestrator.db_service
    return await db_service.get_all_blocked_status()


@router.get("/api/items/{item_id}")
async def get_item_detail(request: Request, item_id: str):
    """Return a standalone HTML page with item details and work log."""
    db = request.app.state.db
    async with db.connect() as conn:
        cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
        item = await cursor.fetchone()
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        item = dict(item)

        cursor = await conn.execute(
            "SELECT * FROM work_log WHERE item_id = ? ORDER BY timestamp",
            (item_id,),
        )
        log_entries = [dict(row) for row in await cursor.fetchall()]

    # Build a simple standalone HTML page
    import html as html_mod
    title = html_mod.escape(item.get("title", ""))
    description = html_mod.escape(item.get("description", "") or "")
    column = html_mod.escape(item.get("column_name", ""))
    commit_msg = html_mod.escape(item.get("commit_message", "") or "")

    log_html = ""
    for entry in log_entries:
        ts = html_mod.escape(str(entry.get("timestamp", "")))
        etype = html_mod.escape(str(entry.get("entry_type", "")))
        content = html_mod.escape(str(entry.get("content", "")))
        log_html += f'<div class="log-entry"><span class="log-meta">[{ts}] {etype}:</span><pre>{content}</pre></div>\n'

    if not log_html:
        log_html = '<div class="log-entry">No work log entries</div>'

    page = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; background: #1a1a2e; color: #e0e0e0; }}
h1 {{ color: #fff; }} .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.85em; background: #333; color: #ccc; margin-right: 8px; }}
.description {{ background: #222; padding: 1rem; border-radius: 6px; margin: 1rem 0; white-space: pre-wrap; }}
.commit-msg {{ background: #1a2e1a; padding: 0.5rem 1rem; border-radius: 6px; margin: 1rem 0; font-family: monospace; }}
.log-entry {{ margin: 0.5rem 0; }} .log-meta {{ color: #888; font-size: 0.85em; }}
pre {{ white-space: pre-wrap; word-break: break-word; margin: 0.25rem 0 0.75rem 0; background: #222; padding: 0.5rem; border-radius: 4px; font-size: 0.9em; }}
</style></head><body>
<h1>{title}</h1>
<span class="badge">{column}</span> <span class="badge">ID: {item_id}</span>
{"<div class='description'>" + description + "</div>" if description else ""}
{"<div class='commit-msg'>Commit: " + commit_msg + "</div>" if commit_msg else ""}
<h2>Work Log</h2>
{log_html}
</body></html>"""
    return HTMLResponse(content=page)


@router.get("/api/items/{item_id}/log")
async def get_work_log(request: Request, item_id: str):
    return await _item_rows(
        request, "SELECT * FROM work_log WHERE item_id = ? ORDER BY timestamp", item_id,
    )


@router.get("/api/yolo-items")
async def get_yolo_items(request: Request):
    """Return item IDs currently running in YOLO mode."""
    orchestrator = request.app.state.orchestrator
    return list(orchestrator.workflow_service._yolo_items)


@router.get("/api/auto-reviewing-items")
async def get_auto_reviewing_items(request: Request):
    """Return item IDs currently being inspected by the auto-review agent.

    Used by the frontend on initial load to attach a "Reviewing" badge to
    cards whose review agent is in flight; live changes arrive via the
    `auto_review_changed` WebSocket event.
    """
    orchestrator = request.app.state.orchestrator
    return list(orchestrator.workflow_service._auto_reviewing)


# --- System Notifications ---

# In-memory notification store (transient — cleared on restart)
_notifications: list[dict] = []


_next_notification_id = 0


_ws_manager_ref = None  # Set during first request via dependency


def add_notification(level: str, message: str, source: str = "", action: dict | None = None) -> dict | None:
    """Add a system notification (error/warning/info). Deduplicates by message.

    action: optional dict with {"label": str, "url": str, "method": str} for an action button.
    Returns the notification or None if duplicate.
    """
    global _next_notification_id
    # Skip if an identical message already exists
    if any(existing["message"] == message for existing in _notifications):
        return None
    _next_notification_id += 1
    entry = {
        "id": _next_notification_id,
        "level": level,
        "message": message,
        "source": source,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if action:
        entry["action"] = action
    _notifications.append(entry)
    _broadcast_notification(entry)
    return entry


def _broadcast_notification(entry: dict) -> None:
    """Best-effort async broadcast (only once a request has captured the ws manager,
    and only from inside a running event loop)."""
    if not _ws_manager_ref:
        return
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_ws_manager_ref.broadcast("notification_added", entry))
    except RuntimeError:
        pass


@router.get("/api/notifications")
async def list_notifications(request: Request):
    global _ws_manager_ref
    if _ws_manager_ref is None:
        _ws_manager_ref = request.app.state.ws_manager
    return _notifications


@router.delete("/api/notifications/{notification_id}")
async def dismiss_notification(notification_id: int):
    global _notifications
    _notifications = [n for n in _notifications if n["id"] != notification_id]
    return {"ok": True}


@router.delete("/api/notifications")
async def clear_notifications():
    global _notifications
    _notifications.clear()
    return {"ok": True}


# --- Shutdown ---

@router.post("/api/shutdown")
async def shutdown_server(request: Request):
    """Gracefully shut down all running agents and then terminate the server.

    The macOS wrapper calls this before killing the server process,
    ensuring Claude agent child processes are properly cleaned up
    (pkill -P only kills direct children, missing grandchildren spawned by the SDK).
    """
    import os
    import signal

    orchestrator = request.app.state.orchestrator
    logger = logging.getLogger(__name__)
    logger.info("Shutdown endpoint called — cleaning up all sessions")

    try:
        await orchestrator.shutdown()
    except Exception as e:
        logger.warning(f"Error during graceful shutdown: {e}")

    # Schedule server termination after returning the response
    async def _deferred_exit():
        await asyncio.sleep(0.5)  # Let the HTTP response flush
        # Use sys.exit() for clean shutdown — allows atexit handlers
        # (e.g. coverage) to flush. The SIGTERM handler kills with SIG_DFL
        # which skips atexit.
        import sys
        sys.exit(0)

    asyncio.create_task(_deferred_exit())

    return {"ok": True, "message": "Shutting down"}


# --- Stale Worktree Cleanup ---

@router.post("/api/cleanup/worktree/{item_id}")
async def cleanup_stale_worktree(item_id: str, request: Request):
    """Clean up a stale worktree and branch for an item."""
    orchestrator = request.app.state.orchestrator
    try:
        result = await orchestrator.workflow_service.cleanup_stale_worktree(item_id)
        # Remove the corresponding notification
        global _notifications
        _notifications = [n for n in _notifications if not (n.get("source") == f"stale-worktree:{item_id}")]
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --- Stats ---

@router.get("/api/stats")
async def get_stats(request: Request):
    """Get usage and activity statistics (optimized with caching)."""
    db = request.app.state.db
    orchestrator = request.app.state.orchestrator

    return await _get_optimized_stats(db, orchestrator)


@router.get("/api/websocket/stats")
async def get_websocket_stats(request: Request):
    """Get WebSocket connection statistics for monitoring."""
    ws_manager = request.app.state.ws_manager
    return ws_manager.get_connection_stats()


# --- WebSocket ---

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    manager = websocket.app.state.ws_manager
    try:
        await manager.connect(websocket)
        try:
            while True:
                # Timeout prevents connections from lingering forever
                # when the client (e.g. a closed wrapper tab) silently
                # drops without sending a close frame.
                try:
                    await asyncio.wait_for(
                        websocket.receive_text(),
                        timeout=120,  # 2 min idle timeout
                    )
                except asyncio.TimeoutError:
                    # No data in 2 minutes — verify the connection is alive.
                    # If the heartbeat already reaped it, receive_text will
                    # raise on the next loop iteration.
                    try:
                        await websocket.send_json({"type": "ping"})
                    except Exception:
                        break
        except WebSocketDisconnect:
            pass
        finally:
            manager.disconnect(websocket)
    except HTTPException:
        # Rate limit exceeded - connection was already closed in manager
        pass


# --- Route groups in their own modules, served under this router ---

from .agent_routes import agent_router  # noqa: E402
from .attachment_routes import attachment_router  # noqa: E402
from .epic_routes import epic_router  # noqa: E402
from .provider_routes import provider_router  # noqa: E402
from .settings_routes import settings_router  # noqa: E402
from .shortcut_routes import shortcut_router  # noqa: E402

for _group in (agent_router, settings_router, provider_router, attachment_router,
               epic_router, shortcut_router):
    router.include_router(_group)
