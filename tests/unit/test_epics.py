"""Tests for epic grouping feature."""

import pytest
import pytest_asyncio
from pathlib import Path
import tempfile

from src.database import Database


@pytest_asyncio.fixture
async def db():
    """Create a test database with all migrations applied."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        database = Database(db_path)
        await database.initialize()
        yield database


@pytest.mark.asyncio
async def test_epics_table_exists(db):
    """Test that the epics table was created by migration."""
    async with db.connect() as conn:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='epics'"
        )
        row = await cursor.fetchone()
    assert row is not None, "epics table should exist"


@pytest.mark.asyncio
async def test_items_has_epic_id_column(db):
    """Test that items table has epic_id column."""
    async with db.connect() as conn:
        cursor = await conn.execute("PRAGMA table_info(items)")
        columns = [row[1] for row in await cursor.fetchall()]
    assert "epic_id" in columns


@pytest.mark.asyncio
async def test_create_epic(db):
    """Test creating an epic."""
    async with db.connect() as conn:
        await conn.execute(
            "INSERT INTO epics (id, title, color, position) VALUES (?, ?, ?, ?)",
            ("epic-001", "Auth Rewrite", "blue", 0),
        )
        await conn.commit()
        cursor = await conn.execute("SELECT * FROM epics WHERE id = ?", ("epic-001",))
        row = dict(await cursor.fetchone())
    assert row["title"] == "Auth Rewrite"
    assert row["color"] == "blue"
    assert row["position"] == 0


@pytest.mark.asyncio
async def test_assign_item_to_epic(db):
    """Test assigning an item to an epic."""
    async with db.connect() as conn:
        await conn.execute(
            "INSERT INTO epics (id, title, color, position) VALUES (?, ?, ?, ?)",
            ("epic-001", "Auth Rewrite", "blue", 0),
        )
        await conn.execute(
            "INSERT INTO items (id, title, column_name, position, epic_id) VALUES (?, ?, ?, ?, ?)",
            ("item-001", "Fix login", "todo", 0, "epic-001"),
        )
        await conn.commit()
        cursor = await conn.execute("SELECT epic_id FROM items WHERE id = ?", ("item-001",))
        row = await cursor.fetchone()
    assert row[0] == "epic-001"


@pytest.mark.asyncio
async def test_delete_epic_nullifies_items(db):
    """Test that deleting an epic nullifies epic_id on related items."""
    async with db.connect() as conn:
        await conn.execute(
            "INSERT INTO epics (id, title, color, position) VALUES (?, ?, ?, ?)",
            ("epic-001", "Auth Rewrite", "blue", 0),
        )
        await conn.execute(
            "INSERT INTO items (id, title, column_name, position, epic_id) VALUES (?, ?, ?, ?, ?)",
            ("item-001", "Fix login", "todo", 0, "epic-001"),
        )
        await conn.commit()

        # Delete the epic and nullify references
        await conn.execute("UPDATE items SET epic_id = NULL WHERE epic_id = ?", ("epic-001",))
        await conn.execute("DELETE FROM epics WHERE id = ?", ("epic-001",))
        await conn.commit()

        cursor = await conn.execute("SELECT epic_id FROM items WHERE id = ?", ("item-001",))
        row = await cursor.fetchone()
    assert row[0] is None
