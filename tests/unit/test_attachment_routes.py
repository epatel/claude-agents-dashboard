"""HTTP endpoint tests for src/web/attachment_routes.py."""

import pytest

from tests.unit.route_fixtures import app_and_db, client_with_item  # noqa: F401  (pytest fixtures; app_and_db backs the others)


class TestAttachments:
    @pytest.mark.asyncio
    async def test_list_attachments_empty(self, client_with_item):
        client, app = client_with_item
        resp = await client.get("/api/items/item001/attachments")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_upload_attachment(self, client_with_item):
        import base64
        client, app = client_with_item
        # minimal 1x1 png
        png_bytes = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
            b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
            b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        b64 = "data:image/png;base64," + base64.b64encode(png_bytes).decode()
        resp = await client.post(
            "/api/items/item001/attachments",
            json={"item_id": "item001", "filename": "test.png", "data": b64},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["item_id"] == "item001"
        assert data["filename"] == "test.png"

    @pytest.mark.asyncio
    async def test_delete_attachment(self, client_with_item):
        import base64
        client, app = client_with_item
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        b64 = base64.b64encode(png_bytes).decode()
        upload_resp = await client.post(
            "/api/items/item001/attachments",
            json={"item_id": "item001", "filename": "del.png", "data": b64},
        )
        att_id = upload_resp.json()["id"]
        resp = await client.delete(f"/api/attachments/{att_id}")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}


# ---------------------------------------------------------------------------
# Item detail (standalone page)
# ---------------------------------------------------------------------------


class TestServeAsset:
    @pytest.mark.asyncio
    async def test_missing_asset_is_404(self, client_with_item):
        client, app = client_with_item
        resp = await client.get("/api/assets/missing.png")
        assert resp.status_code == 404
        assert resp.json() == {"error": "not found"}

    @pytest.mark.asyncio
    async def test_existing_asset_is_served(self, client_with_item):
        client, app = client_with_item
        assets = app.state.data_dir / "assets"
        assets.mkdir(exist_ok=True)
        (assets / "a.txt").write_text("hello")
        resp = await client.get("/api/assets/a.txt")
        assert resp.status_code == 200
        assert resp.text == "hello"
