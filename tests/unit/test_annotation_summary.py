"""Tests for annotation_summary field in attachment upload."""

import pytest
import pytest_asyncio
from pathlib import Path
import tempfile

from src.database import Database


@pytest_asyncio.fixture
async def db_with_item():
    """Create a test database with all migrations applied and a test item."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        db = Database(db_path)
        await db.initialize()

        async with db.connect() as conn:
            await conn.execute(
                """INSERT INTO items (id, title, column_name, position)
                   VALUES (?, ?, ?, ?)""",
                ("item-001", "Test Item", "todo", 0),
            )
            await conn.commit()

        yield db


@pytest.mark.asyncio
async def test_attachment_with_annotation_summary_stored_and_retrieved(db_with_item):
    """Attachment with annotation_summary stores and retrieves it correctly."""
    db = db_with_item
    async with db.connect() as conn:
        await conn.execute(
            "INSERT INTO attachments (item_id, filename, asset_path, annotation_summary) VALUES (?, ?, ?, ?)",
            ("item-001", "annotated.png", "/tmp/annotated.png", "2 arrows, 1 circle"),
        )
        await conn.commit()

        cursor = await conn.execute(
            "SELECT * FROM attachments WHERE item_id = ?",
            ("item-001",),
        )
        row = dict(await cursor.fetchone())

    assert row["annotation_summary"] == "2 arrows, 1 circle"
    assert row["filename"] == "annotated.png"
    assert row["item_id"] == "item-001"


@pytest.mark.asyncio
async def test_attachment_without_annotation_summary_is_null(db_with_item):
    """Attachment without annotation_summary has NULL for that field."""
    db = db_with_item
    async with db.connect() as conn:
        await conn.execute(
            "INSERT INTO attachments (item_id, filename, asset_path) VALUES (?, ?, ?)",
            ("item-001", "plain.png", "/tmp/plain.png"),
        )
        await conn.commit()

        cursor = await conn.execute(
            "SELECT * FROM attachments WHERE item_id = ?",
            ("item-001",),
        )
        row = dict(await cursor.fetchone())

    assert row["annotation_summary"] is None
    assert row["filename"] == "plain.png"
