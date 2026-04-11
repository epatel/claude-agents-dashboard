import asyncio
import base64
import json
import uuid
from pathlib import Path
import time
from typing import Optional

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from pydantic import BaseModel

from ..config import COLUMNS
from ..constants import EPIC_COLORS
from ..models import ItemCreate, ItemUpdate, ItemMove, ClarificationResponse, AgentConfig, EpicCreate, EpicUpdate, new_id
from ..git.operations import get_diff, get_changed_files, get_file_content, get_current_branch

router = APIRouter()

# Simple cache for stats to avoid frequent DB queries
_stats_cache = {"data": None, "timestamp": 0, "ttl": 30}  # 30 second TTL


async def _get_optimized_stats(db, orchestrator):
    """Get stats using optimized combined queries and caching."""
    current_time = time.time()

    # Check cache first
    if (_stats_cache["data"] is not None and
        current_time - _stats_cache["timestamp"] < _stats_cache["ttl"]):
        # Update active agents count (changes frequently)
        _stats_cache["data"]["activity"]["active_agents"] = len(orchestrator.sessions)
        return _stats_cache["data"]

    async with db.connect() as conn:
        # Combined query using CTEs to get most stats in a single roundtrip
        cursor = await conn.execute("""
            WITH token_stats AS (
                SELECT
                    COALESCE(SUM(cost_usd), 0) as total_cost,
                    COALESCE(SUM(input_tokens), 0) as total_input_tokens,
                    COALESCE(SUM(output_tokens), 0) as total_output_tokens,
                    COALESCE(SUM(total_tokens), 0) as total_tokens
                FROM token_usage
            ),
            work_log_stats AS (
                SELECT
                    entry_type,
                    COUNT(*) as count,
                    -- Count completed today
                    SUM(CASE
                        WHEN entry_type = 'system'
                        AND content LIKE 'Agent completed%'
                        AND DATE(timestamp) = DATE('now')
                        THEN 1 ELSE 0
                    END) as completed_today,
                    -- Fallback cost calculation from work log
                    SUM(CASE
                        WHEN entry_type = 'system' AND content LIKE 'Agent completed (cost: $%' THEN
                            CAST(
                                SUBSTR(
                                    SUBSTR(content, INSTR(content, '$') + 1),
                                    1,
                                    INSTR(SUBSTR(content, INSTR(content, '$') + 1), ')') - 1
                                ) AS REAL
                            )
                        ELSE 0
                    END) as fallback_cost
                FROM work_log
                GROUP BY entry_type
            ),
            item_stats AS (
                SELECT
                    column_name,
                    COUNT(*) as count
                FROM items
                WHERE column_name != 'archive'
                GROUP BY column_name
            )
            SELECT
                -- Token stats
                ts.total_cost,
                ts.total_input_tokens,
                ts.total_output_tokens,
                ts.total_tokens,
                -- Work log aggregates
                SUM(wls.fallback_cost) as fallback_total_cost,
                MAX(wls.completed_today) as completed_today,
                SUM(wls.count) as total_messages,
                SUM(CASE WHEN wls.entry_type = 'agent_message' THEN wls.count ELSE 0 END) as agent_messages,
                SUM(CASE WHEN wls.entry_type = 'tool_use' THEN wls.count ELSE 0 END) as tool_calls
            FROM token_stats ts
            CROSS JOIN work_log_stats wls
        """)

        main_row = await cursor.fetchone()

        # Get message counts breakdown
        cursor = await conn.execute("""
            SELECT entry_type, COUNT(*) as count
            FROM work_log
            GROUP BY entry_type
        """)
        message_counts = {row[0]: row[1] for row in await cursor.fetchall()}

        # Get item counts by status
        cursor = await conn.execute("""
            SELECT column_name, COUNT(*) as count
            FROM items
            WHERE column_name != 'archive'
            GROUP BY column_name
        """)
        item_counts = {row[0]: row[1] for row in await cursor.fetchall()}

        # Get recent activity (this changes frequently, so we query it separately)
        cursor = await conn.execute("""
            SELECT entry_type, content, timestamp
            FROM work_log
            ORDER BY timestamp DESC
            LIMIT 10
        """)
        recent_activity = [
            {
                "type": row[0],
                "content": row[1][:100] + "..." if len(row[1]) > 100 else row[1],
                "timestamp": row[2]
            }
            for row in await cursor.fetchall()
        ]

        # Use token_usage data if available, otherwise fallback to work log parsing
        if main_row and main_row[0] is not None and main_row[0] > 0:
            total_cost_usd = main_row[0]
            total_input_tokens = main_row[1]
            total_output_tokens = main_row[2]
            total_tokens = main_row[3]
        else:
            total_cost_usd = main_row[4] if main_row else 0.0  # fallback_total_cost
            total_input_tokens = 0
            total_output_tokens = 0
            total_tokens = 0

        # Build response
        stats_data = {
            "usage": {
                "total_cost_usd": round(total_cost_usd or 0.0, 4),
                "total_messages": main_row[6] if main_row else sum(message_counts.values()),
                "agent_messages": main_row[7] if main_row else message_counts.get('agent_message', 0),
                "tool_calls": main_row[8] if main_row else message_counts.get('tool_use', 0),
                "completed_today": main_row[5] if main_row else 0,
                "total_tokens": total_tokens,
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens
            },
            "activity": {
                "active_agents": len(orchestrator.sessions),
                "items_by_status": item_counts,
                "recent": recent_activity
            },
            "breakdown": message_counts
        }

        # Cache the result
        _stats_cache["data"] = stats_data
        _stats_cache["timestamp"] = current_time

        return stats_data


def _invalidate_stats_cache():
    """Invalidate the stats cache when data changes."""
    _stats_cache["data"] = None
    _stats_cache["timestamp"] = 0


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

    # Get current git branch name
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


@router.post("/api/items")
async def create_item(request: Request, body: ItemCreate):
    db = request.app.state.db
    item_id = new_id()
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
            "INSERT INTO items (id, title, description, column_name, position, model, epic_id, auto_start, start_copy) VALUES (?, ?, ?, 'todo', ?, ?, ?, ?, ?)",
            (item_id, body.title, body.description, position, body.model, body.epic_id, int(body.auto_start), int(body.start_copy)),
        )
        await conn.commit()

        cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
        item = dict(await cursor.fetchone())

    await request.app.state.ws_manager.broadcast("item_created", item)
    _invalidate_stats_cache()  # New item affects stats
    return item


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
    db = request.app.state.db
    async with db.connect() as conn:
        # Find all done items completed on the given date
        cursor = await conn.execute(
            "SELECT id FROM items WHERE column_name = 'done' AND DATE(COALESCE(done_at, updated_at)) = ?",
            (body.date,),
        )
        rows = await cursor.fetchall()
        item_ids = [row[0] for row in rows]

        if not item_ids:
            return {"archived": 0}

        # Move all to archive
        placeholders = ",".join("?" for _ in item_ids)
        await conn.execute(
            f"UPDATE items SET column_name = 'archive', updated_at = datetime('now') WHERE id IN ({placeholders})",
            item_ids,
        )
        await conn.commit()

    # Broadcast move for each archived item
    async with db.connect() as conn:
        for item_id in item_ids:
            cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
            item = dict(await cursor.fetchone())
            await request.app.state.ws_manager.broadcast("item_moved", item)

    _invalidate_stats_cache()
    return {"archived": len(item_ids)}


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
        db_service = request.app.state.orchestrator.db_service
        ns = request.app.state.orchestrator.notification_service
        await db_service.delete_epic(body.epic_id)
        await ns.broadcast_epic_deleted(body.epic_id)
        deleted_epic = True

    _invalidate_stats_cache()
    return {"deleted": len(todo_ids), "epic_deleted": deleted_epic}


@router.post("/api/items/{item_id}/move")
async def move_item(request: Request, item_id: str, body: ItemMove):
    db = request.app.state.db
    orchestrator = request.app.state.orchestrator

    # Clean up agent resources when moving to archive
    if body.column_name == "archive":
        async with db.connect() as conn:
            cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
            old_item = dict(await cursor.fetchone())
        # Stop any running session
        await orchestrator.session_service.cleanup_session(item_id)
        # Clean up worktree and branch
        if old_item.get("worktree_path") and old_item.get("branch_name"):
            from pathlib import Path
            await orchestrator.git_service.cleanup_worktree_and_branch(
                Path(old_item["worktree_path"]), old_item["branch_name"])

    async with db.connect() as conn:
        # Shift positions in target column
        await conn.execute(
            "UPDATE items SET position = position + 1 WHERE column_name = ? AND position >= ? AND id != ?",
            (body.column_name, body.position, item_id),
        )
        # Set done_at when moving to done/archive (if not already set), clear when leaving
        from datetime import datetime, timezone
        done_at_clause = ""
        extra_clauses = ""
        params = [body.column_name, body.position]
        if body.column_name in ("done", "archive"):
            done_at_clause = ", done_at = COALESCE(done_at, ?)"
            params.append(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"))
        else:
            done_at_clause = ", done_at = NULL"
        # Clear git metadata when archiving
        if body.column_name == "archive":
            extra_clauses = ", status = NULL, worktree_path = NULL"
        params.append(item_id)
        await conn.execute(
            f"UPDATE items SET column_name = ?, position = ?{done_at_clause}{extra_clauses}, updated_at = datetime('now') WHERE id = ?",
            params,
        )
        await conn.commit()

        cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
        item = dict(await cursor.fetchone())

    await request.app.state.ws_manager.broadcast("item_moved", item)
    _invalidate_stats_cache()  # Item status change affects stats

    # When an item moves to done/archive, its dependents may become unblocked
    if body.column_name in ("done", "archive"):
        db_service = request.app.state.orchestrator.db_service
        dependent_ids = await db_service.get_dependent_items(item_id)
        if dependent_ids:
            blocked_status = await db_service.get_all_blocked_status()
            await request.app.state.ws_manager.broadcast("blocked_status_changed", {
                "blocked": blocked_status,
            })

    return item


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


# --- Work log ---

@router.get("/api/items/{item_id}/log")
async def get_work_log(request: Request, item_id: str):
    db = request.app.state.db
    async with db.connect() as conn:
        cursor = await conn.execute(
            "SELECT * FROM work_log WHERE item_id = ? ORDER BY timestamp",
            (item_id,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


# --- Agent actions ---

@router.post("/api/items/{item_id}/start")
async def start_agent(request: Request, item_id: str):
    orchestrator = request.app.state.orchestrator
    result = await orchestrator.start_agent(item_id)
    _invalidate_stats_cache()  # Agent start affects stats
    return result


@router.post("/api/items/{item_id}/start-copy")
async def start_copy_agent(request: Request, item_id: str):
    """Copy a todo item and start the copy, leaving the original in todo."""
    orchestrator = request.app.state.orchestrator
    result = await orchestrator.start_copy_agent(item_id)
    _invalidate_stats_cache()
    return result


@router.post("/api/items/{item_id}/cancel")
async def cancel_agent(request: Request, item_id: str):
    orchestrator = request.app.state.orchestrator
    return await orchestrator.cancel_agent(item_id)


@router.post("/api/items/{item_id}/pause")
async def pause_agent(request: Request, item_id: str):
    orchestrator = request.app.state.orchestrator
    return await orchestrator.pause_agent(item_id)


@router.post("/api/items/{item_id}/resume")
async def resume_agent(request: Request, item_id: str):
    orchestrator = request.app.state.orchestrator
    result = await orchestrator.resume_agent(item_id)
    _invalidate_stats_cache()
    return result


@router.post("/api/items/{item_id}/retry")
async def retry_agent(request: Request, item_id: str):
    orchestrator = request.app.state.orchestrator
    return await orchestrator.retry_agent(item_id)


# --- Review ---

@router.get("/api/items/{item_id}/diff")
async def get_item_diff(request: Request, item_id: str):
    db = request.app.state.db
    async with db.connect() as conn:
        cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
        item = dict(await cursor.fetchone())

    if not item.get("branch_name"):
        return {"diff": "", "files": []}

    repo = request.app.state.target_project
    wt = Path(item["worktree_path"]) if item.get("worktree_path") else None
    base = item.get("base_branch")
    base_commit = item.get("base_commit")
    diff = await get_diff(repo, item["branch_name"], base=base, worktree_path=wt, base_commit=base_commit)
    files = await get_changed_files(repo, item["branch_name"], base=base, worktree_path=wt, base_commit=base_commit)
    return {"diff": diff, "files": files}


@router.get("/api/items/{item_id}/files/{file_path:path}")
async def get_item_file(request: Request, item_id: str, file_path: str):
    db = request.app.state.db
    async with db.connect() as conn:
        cursor = await conn.execute("SELECT branch_name FROM items WHERE id = ?", (item_id,))
        item = dict(await cursor.fetchone())

    try:
        content = await get_file_content(request.app.state.target_project, item["branch_name"], file_path)
        return {"content": content}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid file path: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=404, detail="File not found or inaccessible")


@router.get("/api/items/{item_id}/worktree/tree")
async def get_worktree_tree(request: Request, item_id: str, path: str = ""):
    """Return directory tree from an item's worktree for the review file browser."""
    import asyncio as _asyncio
    from ..web.file_routes import scan_directory, validate_file_browser_path
    from ..config import FILE_BROWSER_TREE_DEPTH

    db = request.app.state.db
    async with db.connect() as conn:
        cursor = await conn.execute("SELECT worktree_path FROM items WHERE id = ?", (item_id,))
        row = await cursor.fetchone()

    if not row or not row["worktree_path"]:
        return JSONResponse({"error": "No worktree for this item"}, status_code=404)

    worktree_root = Path(row["worktree_path"])
    if not worktree_root.is_dir():
        return JSONResponse({"error": "Worktree directory not found"}, status_code=404)

    if path:
        try:
            scan_path = validate_file_browser_path(path, worktree_root)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        if not scan_path.is_dir():
            return JSONResponse({"error": "Not a directory"}, status_code=400)
    else:
        scan_path = worktree_root

    tree = await _asyncio.to_thread(scan_directory, scan_path, worktree_root, FILE_BROWSER_TREE_DEPTH)
    return {"root": str(worktree_root), "tree": tree}


@router.get("/api/items/{item_id}/worktree/content")
async def get_worktree_content(request: Request, item_id: str, path: str = ""):
    """Return file content from an item's worktree for the review file browser."""
    import asyncio as _asyncio
    from ..web.file_routes import validate_file_browser_path, read_file_content

    db = request.app.state.db
    async with db.connect() as conn:
        cursor = await conn.execute("SELECT worktree_path FROM items WHERE id = ?", (item_id,))
        row = await cursor.fetchone()

    if not row or not row["worktree_path"]:
        return JSONResponse({"error": "No worktree for this item"}, status_code=404)

    worktree_root = Path(row["worktree_path"])
    if not worktree_root.is_dir():
        return JSONResponse({"error": "Worktree directory not found"}, status_code=404)

    if not path:
        return JSONResponse({"error": "Path parameter required"}, status_code=400)

    try:
        file_path = validate_file_browser_path(path, worktree_root)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    if not file_path.exists():
        return JSONResponse({"error": f"File not found: {path}"}, status_code=404)
    # Block reading symlinks to prevent following links outside the worktree
    original_path = worktree_root / path
    if original_path.is_symlink():
        return JSONResponse({"error": "Symlinks cannot be read for security reasons"}, status_code=403)
    if not file_path.is_file():
        return JSONResponse({"error": f"Not a file: {path}"}, status_code=400)

    result = await _asyncio.to_thread(read_file_content, file_path, path)
    return result


@router.get("/api/items/{item_id}/clarification")
async def get_pending_clarification(request: Request, item_id: str):
    db = request.app.state.db
    async with db.connect() as conn:
        cursor = await conn.execute(
            "SELECT * FROM clarifications WHERE item_id = ? AND response IS NULL ORDER BY id DESC LIMIT 1",
            (item_id,),
        )
        row = await cursor.fetchone()
        if row:
            return dict(row)
        return {"prompt": None}


@router.post("/api/items/{item_id}/approve")
async def approve_item(request: Request, item_id: str):
    from ..config import HTTP_REQUEST_TIMEOUT
    import asyncio

    orchestrator = request.app.state.orchestrator

    try:
        # Add HTTP-level timeout that's slightly longer than git merge timeout
        result = await asyncio.wait_for(
            orchestrator.approve_item(item_id),
            timeout=HTTP_REQUEST_TIMEOUT
        )
        _invalidate_stats_cache()  # Item approval affects stats
        return result
    except asyncio.TimeoutError:
        # Return error response for HTTP timeout
        from fastapi import HTTPException
        raise HTTPException(
            status_code=504,
            detail="Request timed out - merge operation took too long"
        )


class RequestChangesBody(BaseModel):
    comments: list[str]

@router.post("/api/items/{item_id}/request-changes")
async def request_changes(request: Request, item_id: str, body: RequestChangesBody):
    orchestrator = request.app.state.orchestrator
    return await orchestrator.request_changes(item_id, body.comments)


@router.post("/api/items/{item_id}/cancel-review")
async def cancel_review(request: Request, item_id: str):
    orchestrator = request.app.state.orchestrator
    return await orchestrator.cancel_review(item_id)


@router.post("/api/items/{item_id}/retry-merge")
async def retry_merge(request: Request, item_id: str):
    """Move item back to review and re-trigger approve."""
    orchestrator = request.app.state.orchestrator
    # Move back to review first
    item = await orchestrator.db_service.update_item(item_id, column_name="review", status=None)
    await orchestrator.ws_manager.broadcast("item_moved", item)
    # Re-trigger approve
    return await orchestrator.approve_item(item_id)


@router.post("/api/items/{item_id}/clarify")
async def submit_clarification(request: Request, item_id: str, body: ClarificationResponse):
    orchestrator = request.app.state.orchestrator
    return await orchestrator.submit_clarification(item_id, body.response)


@router.post("/api/items/{item_id}/approve-command")
async def approve_command(item_id: str, request: Request):
    """Approve or deny a command access request from an agent."""
    data = await request.json()
    approved = data.get("approved", False)
    response = "approved" if approved else "denied"

    orchestrator = request.app.state.orchestrator
    await orchestrator.submit_clarification(item_id, response)

    return {"status": "ok", "decision": response}


# --- Agent config ---

@router.get("/api/config")
async def get_config(request: Request):
    db = request.app.state.db
    async with db.connect() as conn:
        cursor = await conn.execute("SELECT * FROM agent_config WHERE id = 1")
        row = await cursor.fetchone()
        return dict(row) if row else {}


@router.put("/api/config")
async def update_config(request: Request, body: AgentConfig):
    db = request.app.state.db
    async with db.connect() as conn:
        await conn.execute(
            "UPDATE agent_config SET system_prompt = ?, tools = ?, model = ?, project_context = ?, mcp_servers = ?, mcp_enabled = ?, plugins = ?, allowed_commands = ?, bash_yolo = ?, allowed_builtin_tools = ?, flame_enabled = ?, flame_intensity_multiplier = ?, updated_at = datetime('now') WHERE id = 1",
            (body.system_prompt, body.tools, body.model, body.project_context, body.mcp_servers, body.mcp_enabled, body.plugins, body.allowed_commands, body.bash_yolo, body.allowed_builtin_tools, body.flame_enabled, body.flame_intensity_multiplier),
        )
        await conn.commit()
        cursor = await conn.execute("SELECT * FROM agent_config WHERE id = 1")
        return dict(await cursor.fetchone())


@router.get("/api/config/available-tools")
async def get_available_tools():
    from ..constants import OPTIONAL_BUILTIN_TOOLS
    return OPTIONAL_BUILTIN_TOOLS


@router.get("/api/yolo-items")
async def get_yolo_items(request: Request):
    """Return item IDs currently running in YOLO mode."""
    orchestrator = request.app.state.orchestrator
    return list(orchestrator.workflow_service._yolo_items)


# --- Attachments ---

@router.get("/api/items/{item_id}/attachments")
async def list_attachments(request: Request, item_id: str):
    db = request.app.state.db
    async with db.connect() as conn:
        cursor = await conn.execute(
            "SELECT * FROM attachments WHERE item_id = ? ORDER BY created_at",
            (item_id,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


class UploadAnnotation(BaseModel):
    item_id: str
    filename: str
    data: str  # base64 PNG data URL
    annotation_summary: str | None = None


@router.post("/api/items/{item_id}/attachments")
async def upload_attachment(request: Request, item_id: str, body: UploadAnnotation):
    """Upload an annotated image (base64 PNG)."""
    db = request.app.state.db
    assets_dir = request.app.state.data_dir / "assets"
    assets_dir.mkdir(exist_ok=True)

    # Decode base64 data URL
    data = body.data
    if data.startswith("data:"):
        data = data.split(",", 1)[1]
    img_bytes = base64.b64decode(data)

    # Save to assets
    asset_filename = f"{uuid.uuid4().hex[:12]}_{body.filename}"
    asset_path = assets_dir / asset_filename
    asset_path.write_bytes(img_bytes)

    # Store in DB
    async with db.connect() as conn:
        await conn.execute(
            "INSERT INTO attachments (item_id, filename, asset_path, annotation_summary) VALUES (?, ?, ?, ?)",
            (item_id, body.filename, str(asset_path), body.annotation_summary),
        )
        await conn.commit()
        cursor = await conn.execute(
            "SELECT * FROM attachments WHERE item_id = ? ORDER BY id DESC LIMIT 1",
            (item_id,),
        )
        attachment = dict(await cursor.fetchone())

    return attachment


@router.get("/api/assets/{filename}")
async def serve_asset(request: Request, filename: str):
    assets_dir = request.app.state.data_dir / "assets"
    file_path = assets_dir / filename
    if not file_path.exists() or not file_path.is_relative_to(assets_dir):
        return {"error": "not found"}
    return FileResponse(file_path)


@router.delete("/api/attachments/{attachment_id}")
async def delete_attachment(request: Request, attachment_id: int):
    db = request.app.state.db
    async with db.connect() as conn:
        cursor = await conn.execute("SELECT * FROM attachments WHERE id = ?", (attachment_id,))
        row = await cursor.fetchone()
        if row:
            # Delete file
            asset_path = Path(dict(row)["asset_path"])
            if asset_path.exists():
                asset_path.unlink()
            await conn.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
            await conn.commit()
    return {"ok": True}


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
    for existing in _notifications:
        if existing["message"] == message:
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
    # Best-effort async broadcast
    if _ws_manager_ref:
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_ws_manager_ref.broadcast("notification_added", entry))
        except RuntimeError:
            pass
    return entry


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



# --- Epics ---

@router.get("/api/epics")
async def get_epics(request: Request):
    """Get all epics with progress stats."""
    db_service = request.app.state.orchestrator.db_service
    epics = await db_service.get_epics()
    progress = await db_service.get_epic_progress()
    for epic in epics:
        epic["progress"] = progress.get(epic["id"], {
            "todo": 0, "doing": 0, "questions": 0, "review": 0, "done": 0, "archive": 0, "total": 0
        })
    return epics


@router.get("/api/epics/colors")
async def get_epic_colors():
    """Get the preset epic color palette."""
    return EPIC_COLORS


@router.post("/api/epics")
async def create_epic(request: Request, body: EpicCreate):
    """Create a new epic."""
    db_service = request.app.state.orchestrator.db_service
    ns = request.app.state.orchestrator.notification_service
    epic = await db_service.create_epic(body.title, body.color)
    await ns.broadcast_epic_created(epic)
    _invalidate_stats_cache()
    return epic


@router.put("/api/epics/{epic_id}")
async def update_epic(request: Request, epic_id: str, body: EpicUpdate):
    """Update an epic."""
    db_service = request.app.state.orchestrator.db_service
    ns = request.app.state.orchestrator.notification_service
    kwargs = body.model_dump(exclude_unset=True)
    epic = await db_service.update_epic(epic_id, **kwargs)
    if not epic:
        raise HTTPException(status_code=404, detail="Epic not found")
    await ns.broadcast_epic_updated(epic)
    return epic


@router.delete("/api/epics/{epic_id}")
async def delete_epic(request: Request, epic_id: str):
    """Delete an epic (nullifies epic_id on related items)."""
    db_service = request.app.state.orchestrator.db_service
    ns = request.app.state.orchestrator.notification_service
    epic = await db_service.delete_epic(epic_id)
    if not epic:
        raise HTTPException(status_code=404, detail="Epic not found")
    await ns.broadcast_epic_deleted(epic_id)
    _invalidate_stats_cache()
    return {"success": True}


# --- Shortcuts ---

# In-memory process tracker: shortcut_id → { process, output, status, exit_code }
_shortcut_processes: dict[str, dict] = {}


def _shortcuts_file(request: Request) -> Path:
    """Return path to shortcuts JSON file in data dir."""
    return request.app.state.data_dir / "shortcuts.json"


def _load_shortcuts(path: Path) -> list[dict]:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return []


def _save_shortcuts(path: Path, shortcuts: list[dict]):
    path.write_text(json.dumps(shortcuts, indent=2))


@router.get("/api/shortcuts")
async def list_shortcuts(request: Request):
    return _load_shortcuts(_shortcuts_file(request))


class ShortcutCreate(BaseModel):
    name: str
    command: str


@router.post("/api/shortcuts")
async def create_shortcut(request: Request, body: ShortcutCreate):
    path = _shortcuts_file(request)
    shortcuts = _load_shortcuts(path)
    sc = {"id": uuid.uuid4().hex[:10], "name": body.name, "command": body.command}
    shortcuts.append(sc)
    _save_shortcuts(path, shortcuts)
    return sc


class ShortcutUpdate(BaseModel):
    name: str | None = None
    command: str | None = None


@router.put("/api/shortcuts/{shortcut_id}")
async def update_shortcut(request: Request, shortcut_id: str, body: ShortcutUpdate):
    path = _shortcuts_file(request)
    shortcuts = _load_shortcuts(path)
    sc = next((s for s in shortcuts if s["id"] == shortcut_id), None)
    if not sc:
        raise HTTPException(status_code=404, detail="Shortcut not found")
    if body.name is not None:
        sc["name"] = body.name
    if body.command is not None:
        sc["command"] = body.command
    _save_shortcuts(path, shortcuts)
    return sc


@router.delete("/api/shortcuts/{shortcut_id}")
async def delete_shortcut(request: Request, shortcut_id: str):
    path = _shortcuts_file(request)
    shortcuts = _load_shortcuts(path)
    shortcuts = [s for s in shortcuts if s["id"] != shortcut_id]
    _save_shortcuts(path, shortcuts)
    # Kill running process if any
    proc_info = _shortcut_processes.pop(shortcut_id, None)
    if proc_info and proc_info.get("process"):
        try:
            proc_info["process"].kill()
        except ProcessLookupError:
            pass
    return {"ok": True}


@router.post("/api/shortcuts/{shortcut_id}/run")
async def run_shortcut(request: Request, shortcut_id: str):
    """Run a shortcut command as a subprocess."""
    path = _shortcuts_file(request)
    shortcuts = _load_shortcuts(path)
    sc = next((s for s in shortcuts if s["id"] == shortcut_id), None)
    if not sc:
        raise HTTPException(status_code=404, detail="Shortcut not found")

    # Kill previous process for this shortcut if still running
    existing = _shortcut_processes.get(shortcut_id)
    if existing and existing.get("process") and existing["process"].returncode is None:
        try:
            existing["process"].kill()
        except ProcessLookupError:
            pass

    # Start the subprocess
    cwd = str(request.app.state.target_project)
    proc = await asyncio.create_subprocess_shell(
        sc["command"],
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=cwd,
    )

    proc_info = {
        "process": proc,
        "output": "",
        "status": "running",
        "exit_code": None,
    }
    _shortcut_processes[shortcut_id] = proc_info

    # Background task to read output
    async def _read_output():
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                # Stop appending once the process has been stopped by the user
                if proc_info.get("_stopped"):
                    continue
                proc_info["output"] += line.decode("utf-8", errors="replace")
                # Cap output at 500KB
                if len(proc_info["output"]) > 500_000:
                    proc_info["output"] = proc_info["output"][-400_000:]
            await proc.wait()
            # Don't overwrite status if already stopped by user
            if not proc_info.get("_stopped"):
                proc_info["exit_code"] = proc.returncode
                proc_info["status"] = "done" if proc.returncode == 0 else "failed"
        except Exception as e:
            if not proc_info.get("_stopped"):
                proc_info["output"] += f"\n[Error reading output: {e}]"
                proc_info["status"] = "failed"
                proc_info["exit_code"] = -1

    asyncio.create_task(_read_output())
    return {"status": "started"}


@router.get("/api/shortcuts/{shortcut_id}/output")
async def get_shortcut_output(shortcut_id: str):
    """Get current output and status of a running shortcut."""
    proc_info = _shortcut_processes.get(shortcut_id)
    if not proc_info:
        return {"status": "idle", "output": "", "exit_code": None}
    return {
        "status": proc_info["status"],
        "output": proc_info["output"],
        "exit_code": proc_info["exit_code"],
    }


@router.post("/api/shortcuts/{shortcut_id}/stop")
async def stop_shortcut(shortcut_id: str):
    """Stop a running shortcut, keeping its output log."""
    proc_info = _shortcut_processes.get(shortcut_id)
    if not proc_info:
        return {"ok": False, "detail": "No process found"}
    # Set _stopped flag first so _read_output() stops appending late output
    proc_info["_stopped"] = True
    if proc_info.get("process") and proc_info["process"].returncode is None:
        try:
            proc_info["process"].kill()
        except ProcessLookupError:
            pass
        # Wait briefly for process to finish
        try:
            await asyncio.wait_for(proc_info["process"].wait(), timeout=2.0)
        except asyncio.TimeoutError:
            pass
    # Yield once so _read_output() can see the _stopped flag and drain
    await asyncio.sleep(0)
    proc_info["output"] += "\n\n======= STOPPED BY USER =======\n"
    proc_info["status"] = "stopped"
    proc_info["exit_code"] = proc_info.get("exit_code") or -15
    return {"ok": True}


@router.post("/api/shortcuts/{shortcut_id}/reset")
async def reset_shortcut(shortcut_id: str):
    """Reset a shortcut: kill any running process and clear its output log."""
    proc_info = _shortcut_processes.pop(shortcut_id, None)
    if proc_info and proc_info.get("process"):
        try:
            proc_info["process"].kill()
        except ProcessLookupError:
            pass
    return {"ok": True}


# --- WebSocket ---

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    manager = websocket.app.state.ws_manager
    try:
        await manager.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(websocket)
    except HTTPException:
        # Rate limit exceeded - connection was already closed in manager
        pass
