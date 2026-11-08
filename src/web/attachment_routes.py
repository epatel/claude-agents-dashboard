"""Item attachments (screenshots / annotations) and the asset files they point at."""

import base64
import uuid
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from .route_helpers import _item_rows

attachment_router = APIRouter()


# --- Attachments ---

@attachment_router.get("/api/items/{item_id}/attachments")
async def list_attachments(request: Request, item_id: str):
    return await _item_rows(
        request, "SELECT * FROM attachments WHERE item_id = ? ORDER BY created_at", item_id,
    )


class UploadAnnotation(BaseModel):
    item_id: str
    filename: str
    data: str  # base64 PNG data URL
    annotation_summary: str | None = None


@attachment_router.post("/api/items/{item_id}/attachments")
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


@attachment_router.get("/api/assets/{filename}")
async def serve_asset(request: Request, filename: str):
    assets_dir = request.app.state.data_dir / "assets"
    file_path = assets_dir / filename
    if not file_path.exists() or not file_path.is_relative_to(assets_dir):
        return {"error": "not found"}
    return FileResponse(file_path)


@attachment_router.delete("/api/attachments/{attachment_id}")
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
