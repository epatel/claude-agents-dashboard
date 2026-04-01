import base64
import uuid
from pathlib import Path
import time
from typing import Optional

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

from ..config import COLUMNS
from ..models import ItemCreate, ItemUpdate, ItemMove, ClarificationResponse, AgentConfig, new_id
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
    async with db.connect() as conn:
        cursor = await conn.execute(
            "SELECT * FROM items ORDER BY column_name, position"
        )
        rows = await cursor.fetchall()
        items = [dict(row) for row in rows]

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

        await conn.execute(
            "INSERT INTO items (id, title, description, column_name, position, model) VALUES (?, ?, ?, 'todo', ?, ?)",
            (item_id, body.title, body.description, position, body.model),
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
    return item


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
        # Path validation error - return 400 Bad Request
        raise HTTPException(status_code=400, detail=f"Invalid file path: {str(e)}")
    except Exception as e:
        # Other errors (e.g., file not found, git errors) - return 404
        raise HTTPException(status_code=404, detail="File not found or inaccessible")


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
            "UPDATE agent_config SET system_prompt = ?, tools = ?, model = ?, project_context = ?, mcp_servers = ?, mcp_enabled = ?, plugins = ?, allowed_commands = ?, bash_yolo = ?, allowed_builtin_tools = ?, updated_at = datetime('now') WHERE id = 1",
            (body.system_prompt, body.tools, body.model, body.project_context, body.mcp_servers, body.mcp_enabled, body.plugins, body.allowed_commands, body.bash_yolo, body.allowed_builtin_tools),
        )
        await conn.commit()
        cursor = await conn.execute("SELECT * FROM agent_config WHERE id = 1")
        return dict(await cursor.fetchone())


@router.get("/api/config/available-tools")
async def get_available_tools():
    from ..constants import OPTIONAL_BUILTIN_TOOLS
    return OPTIONAL_BUILTIN_TOOLS


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


def add_notification(level: str, message: str, source: str = "") -> dict | None:
    """Add a system notification (error/warning/info). Deduplicates by message. Returns the notification or None if duplicate."""
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
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(websocket)
    except HTTPException:
        # Rate limit exceeded - connection was already closed in manager
        pass
