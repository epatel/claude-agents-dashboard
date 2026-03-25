import base64
import uuid
from pathlib import Path

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

from ..config import COLUMNS
from ..models import ItemCreate, ItemUpdate, ItemMove, ClarificationResponse, AgentConfig, new_id
from ..git.operations import get_diff, get_changed_files, get_file_content

router = APIRouter()


# --- Board page ---

@router.get("/", response_class=HTMLResponse)
async def board_page(request: Request):
    db = request.app.state.db
    async with db.connect() as conn:
        cursor = await conn.execute(
            "SELECT * FROM items WHERE column_name != 'archive' ORDER BY column_name, position"
        )
        rows = await cursor.fetchall()
        items = [dict(row) for row in rows]

    return request.app.state.templates.TemplateResponse(
        request=request,
        name="board.html",
        context={
            "columns": COLUMNS,
            "items": items,
            "project_name": request.app.state.target_project.name,
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
    db = request.app.state.db
    async with db.connect() as conn:
        # Get item info for cleanup
        cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
        item = await cursor.fetchone()
        if item:
            item = dict(item)

        # Delete attachment files
        cursor2 = await conn.execute("SELECT asset_path FROM attachments WHERE item_id = ?", (item_id,))
        for row in await cursor2.fetchall():
            p = Path(row[0])
            if p.exists():
                p.unlink()

        await conn.execute("DELETE FROM attachments WHERE item_id = ?", (item_id,))
        await conn.execute("DELETE FROM work_log WHERE item_id = ?", (item_id,))
        await conn.execute("DELETE FROM review_comments WHERE item_id = ?", (item_id,))
        await conn.execute("DELETE FROM clarifications WHERE item_id = ?", (item_id,))
        await conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        await conn.commit()

    # Cancel running agent if any
    orchestrator = request.app.state.orchestrator
    session = orchestrator.sessions.pop(item_id, None)
    if session:
        await session.cancel()

    # Clean up worktree and branch
    if item and item.get("worktree_path") and item.get("branch_name"):
        from ..git.worktree import cleanup_worktree
        try:
            await cleanup_worktree(
                request.app.state.target_project,
                Path(item["worktree_path"]),
                item["branch_name"],
            )
        except Exception:
            pass

    await request.app.state.ws_manager.broadcast("item_deleted", {"id": item_id})
    return {"ok": True}


@router.post("/api/items/{item_id}/move")
async def move_item(request: Request, item_id: str, body: ItemMove):
    db = request.app.state.db
    async with db.connect() as conn:
        # Shift positions in target column
        await conn.execute(
            "UPDATE items SET position = position + 1 WHERE column_name = ? AND position >= ? AND id != ?",
            (body.column_name, body.position, item_id),
        )
        await conn.execute(
            "UPDATE items SET column_name = ?, position = ?, updated_at = datetime('now') WHERE id = ?",
            (body.column_name, body.position, item_id),
        )
        await conn.commit()

        cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
        item = dict(await cursor.fetchone())

    await request.app.state.ws_manager.broadcast("item_moved", item)
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
    return await orchestrator.start_agent(item_id)


@router.post("/api/items/{item_id}/cancel")
async def cancel_agent(request: Request, item_id: str):
    orchestrator = request.app.state.orchestrator
    return await orchestrator.cancel_agent(item_id)


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
    diff = await get_diff(repo, item["branch_name"], worktree_path=wt)
    files = await get_changed_files(repo, item["branch_name"], worktree_path=wt)
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
    orchestrator = request.app.state.orchestrator
    return await orchestrator.approve_item(item_id)


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


@router.post("/api/items/{item_id}/clarify")
async def submit_clarification(request: Request, item_id: str, body: ClarificationResponse):
    orchestrator = request.app.state.orchestrator
    return await orchestrator.submit_clarification(item_id, body.response)


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
            "UPDATE agent_config SET system_prompt = ?, tools = ?, model = ?, project_context = ?, mcp_servers = ?, mcp_enabled = ?, plugins = ?, updated_at = datetime('now') WHERE id = 1",
            (body.system_prompt, body.tools, body.model, body.project_context, body.mcp_servers, body.mcp_enabled, body.plugins),
        )
        await conn.commit()
        cursor = await conn.execute("SELECT * FROM agent_config WHERE id = 1")
        return dict(await cursor.fetchone())


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
            "INSERT INTO attachments (item_id, filename, asset_path) VALUES (?, ?, ?)",
            (item_id, body.filename, str(asset_path)),
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


# --- Stats ---

@router.get("/api/stats")
async def get_stats(request: Request):
    """Get usage and activity statistics."""
    db = request.app.state.db
    orchestrator = request.app.state.orchestrator

    async with db.connect() as conn:
        # Get usage statistics from token_usage table (preferred) and fallback to work log
        cursor = await conn.execute("""
            SELECT
                SUM(COALESCE(cost_usd, 0)) as total_cost,
                SUM(COALESCE(input_tokens, 0)) as total_input_tokens,
                SUM(COALESCE(output_tokens, 0)) as total_output_tokens,
                SUM(COALESCE(total_tokens, 0)) as total_tokens
            FROM token_usage
        """)
        row = await cursor.fetchone()

        # Use token_usage table data if available
        if row and row[0] is not None:
            total_cost_usd = row[0] or 0.0
            total_input_tokens = row[1] or 0
            total_output_tokens = row[2] or 0
            total_tokens = row[3] or 0
        else:
            # Fallback to parsing work log entries for cost
            cursor = await conn.execute("""
                SELECT SUM(
                    CASE
                        WHEN content LIKE 'Agent completed (cost: $%' THEN
                            CAST(
                                SUBSTR(
                                    SUBSTR(content, INSTR(content, '$') + 1),
                                    1,
                                    INSTR(SUBSTR(content, INSTR(content, '$') + 1), ')') - 1
                                ) AS REAL
                            )
                        ELSE 0
                    END
                ) as total_cost
                FROM work_log
                WHERE entry_type = 'system' AND content LIKE 'Agent completed%'
            """)
            row = await cursor.fetchone()
            total_cost_usd = row[0] if row and row[0] else 0.0
            total_input_tokens = 0
            total_output_tokens = 0
            total_tokens = 0

        # Count total messages by type
        cursor = await conn.execute("""
            SELECT entry_type, COUNT(*) as count
            FROM work_log
            GROUP BY entry_type
        """)
        message_counts = {row[0]: row[1] for row in await cursor.fetchall()}

        # Count tool calls
        tool_calls = message_counts.get('tool_use', 0)

        # Count agent messages
        agent_messages = message_counts.get('agent_message', 0)

        # Count active agents
        active_agents = len(orchestrator.sessions)

        # Count items by status
        cursor = await conn.execute("""
            SELECT column_name, COUNT(*) as count
            FROM items
            WHERE column_name != 'archive'
            GROUP BY column_name
        """)
        item_counts = {row[0]: row[1] for row in await cursor.fetchall()}

        # Count completed items today
        cursor = await conn.execute("""
            SELECT COUNT(*) as count
            FROM work_log
            WHERE entry_type = 'system'
            AND content LIKE 'Agent completed%'
            AND DATE(timestamp) = DATE('now')
        """)
        row = await cursor.fetchone()
        completed_today = row[0] if row else 0

        # Get recent activity (last 10 entries)
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

    return {
        "usage": {
            "total_cost_usd": round(total_cost_usd, 4),
            "total_messages": sum(message_counts.values()),
            "agent_messages": agent_messages,
            "tool_calls": tool_calls,
            "completed_today": completed_today,
            "total_tokens": total_tokens,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens
        },
        "activity": {
            "active_agents": active_agents,
            "items_by_status": item_counts,
            "recent": recent_activity
        },
        "breakdown": message_counts
    }


# --- WebSocket ---

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    manager = websocket.app.state.ws_manager
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
