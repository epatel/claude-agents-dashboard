"""Agent actions on an item: start / pause / resume / retry / cancel, its diff,
peek and worktree files, clarifications, and review (approve, request changes,
retry merge, approve command)."""

from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from ..domain.item_state import Event
from ..models import ClarificationResponse
from ..git.operations import get_diff, get_changed_files, get_file_content
from .stats_cache import _invalidate_stats_cache

agent_router = APIRouter()


# --- Agent actions ---

@agent_router.post("/api/items/{item_id}/start")
async def start_agent(request: Request, item_id: str):
    orchestrator = request.app.state.orchestrator
    result = await orchestrator.start_agent(item_id)
    _invalidate_stats_cache()  # Agent start affects stats
    return result


@agent_router.post("/api/items/{item_id}/start-copy")
async def start_copy_agent(request: Request, item_id: str):
    """Copy a todo item and start the copy, leaving the original in todo."""
    orchestrator = request.app.state.orchestrator
    result = await orchestrator.start_copy_agent(item_id)
    _invalidate_stats_cache()
    return result


@agent_router.post("/api/items/{item_id}/cancel")
async def cancel_agent(request: Request, item_id: str):
    orchestrator = request.app.state.orchestrator
    return await orchestrator.cancel_agent(item_id)


class PauseAgentBody(BaseModel):
    message: Optional[str] = None


@agent_router.post("/api/items/{item_id}/pause")
async def pause_agent(
    request: Request,
    item_id: str,
    body: Optional[PauseAgentBody] = None,
):
    orchestrator = request.app.state.orchestrator
    message = body.message if body else None
    return await orchestrator.pause_agent(item_id, message)


class ResumeAgentBody(BaseModel):
    message: Optional[str] = None


@agent_router.post("/api/items/{item_id}/resume")
async def resume_agent(
    request: Request,
    item_id: str,
    body: Optional[ResumeAgentBody] = None,
):
    orchestrator = request.app.state.orchestrator
    message = body.message if body else None
    result = await orchestrator.resume_agent(item_id, message)
    _invalidate_stats_cache()
    return result


@agent_router.post("/api/items/{item_id}/retry")
async def retry_agent(request: Request, item_id: str):
    orchestrator = request.app.state.orchestrator
    return await orchestrator.retry_agent(item_id)


# --- Review ---

def _resolve_item_repo_path(request: Request, item_repo: Optional[str]) -> Path:
    """Return the git repo path for an item in either mode."""
    target = request.app.state.target_project
    repos = request.app.state.repos
    if repos and item_repo:
        return target / item_repo
    return target


@agent_router.get("/api/items/{item_id}/diff")
async def get_item_diff(request: Request, item_id: str):
    db = request.app.state.db
    async with db.connect() as conn:
        cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
        item = dict(await cursor.fetchone())

    if not item.get("branch_name"):
        return {"diff": "", "files": []}

    repo = _resolve_item_repo_path(request, item.get("repo"))
    wt = Path(item["worktree_path"]) if item.get("worktree_path") else None
    base = item.get("base_branch")
    base_commit = item.get("base_commit")
    diff = await get_diff(repo, item["branch_name"], base=base, worktree_path=wt, base_commit=base_commit)
    files = await get_changed_files(repo, item["branch_name"], base=base, worktree_path=wt, base_commit=base_commit)
    return {"diff": diff, "files": files}


@agent_router.get("/api/items/{item_id}/peek")
async def peek_worktrees(request: Request, item_id: str,
                         target_item_id: Optional[str] = None,
                         path: Optional[str] = None):
    """Read-only peek at other agents' in-flight worktree changes.

    Backs the Kimi runtime's `peek_worktree` board tool (which reaches the
    dashboard over HTTP rather than through an in-process MCP server); the
    Claude runtime calls the same code directly via the SDK tool.
    """
    orchestrator = request.app.state.orchestrator
    text = await orchestrator.peek_worktree(item_id, target_item_id, path)
    return {"text": text}


@agent_router.get("/api/items/{item_id}/files/{file_path:path}")
async def get_item_file(request: Request, item_id: str, file_path: str):
    db = request.app.state.db
    async with db.connect() as conn:
        cursor = await conn.execute("SELECT branch_name, repo FROM items WHERE id = ?", (item_id,))
        item = dict(await cursor.fetchone())

    try:
        repo_path = _resolve_item_repo_path(request, item.get("repo"))
        content = await get_file_content(repo_path, item["branch_name"], file_path)
        return {"content": content}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid file path: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=404, detail="File not found or inaccessible")


async def _item_worktree_root(request: Request, item_id: str):
    """The item's worktree directory, or a 404 JSONResponse if it has none on disk."""
    db = request.app.state.db
    async with db.connect() as conn:
        cursor = await conn.execute("SELECT worktree_path FROM items WHERE id = ?", (item_id,))
        row = await cursor.fetchone()

    if not row or not row["worktree_path"]:
        return JSONResponse({"error": "No worktree for this item"}, status_code=404)

    worktree_root = Path(row["worktree_path"])
    if not worktree_root.is_dir():
        return JSONResponse({"error": "Worktree directory not found"}, status_code=404)
    return worktree_root


@agent_router.get("/api/items/{item_id}/worktree/tree")
async def get_worktree_tree(request: Request, item_id: str, path: str = ""):
    """Return directory tree from an item's worktree for the review file browser."""
    import asyncio as _asyncio
    from ..web.file_routes import scan_directory, validate_file_browser_path
    from ..config import FILE_BROWSER_TREE_DEPTH

    worktree_root = await _item_worktree_root(request, item_id)
    if isinstance(worktree_root, JSONResponse):
        return worktree_root

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


@agent_router.get("/api/items/{item_id}/worktree/content")
async def get_worktree_content(request: Request, item_id: str, path: str = ""):
    """Return file content from an item's worktree for the review file browser."""
    import asyncio as _asyncio
    from ..web.file_routes import validate_file_browser_path, read_file_content

    worktree_root = await _item_worktree_root(request, item_id)
    if isinstance(worktree_root, JSONResponse):
        return worktree_root

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


@agent_router.get("/api/items/{item_id}/clarification")
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


@agent_router.post("/api/items/{item_id}/approve")
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


@agent_router.post("/api/items/{item_id}/request-changes")
async def request_changes(request: Request, item_id: str, body: RequestChangesBody):
    orchestrator = request.app.state.orchestrator
    return await orchestrator.request_changes(item_id, body.comments)


@agent_router.post("/api/items/{item_id}/cancel-review")
async def cancel_review(request: Request, item_id: str):
    orchestrator = request.app.state.orchestrator
    return await orchestrator.cancel_review(item_id)


@agent_router.post("/api/items/{item_id}/retry-merge")
async def retry_merge(request: Request, item_id: str):
    """Move item back to review and re-trigger approve."""
    orchestrator = request.app.state.orchestrator
    # Move back to review first
    item = await orchestrator.item_repository.transition(item_id, Event.RETRY_MERGE)
    await orchestrator.ws_manager.broadcast("item_moved", item)
    # Re-trigger approve
    return await orchestrator.approve_item(item_id)


@agent_router.post("/api/items/{item_id}/clarify")
async def submit_clarification(request: Request, item_id: str, body: ClarificationResponse):
    orchestrator = request.app.state.orchestrator
    return await orchestrator.submit_clarification(item_id, body.response)


@agent_router.post("/api/items/{item_id}/approve-command")
async def approve_command(item_id: str, request: Request):
    """Approve or deny a command access request from an agent."""
    data = await request.json()
    approved = data.get("approved", False)
    response = "approved" if approved else "denied"

    orchestrator = request.app.state.orchestrator
    await orchestrator.submit_clarification(item_id, response)

    return {"status": "ok", "decision": response}
