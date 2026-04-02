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


from src.services.database_service import DatabaseService


@pytest_asyncio.fixture
async def db_service(db):
    """Create a DatabaseService instance."""
    return DatabaseService(db)


@pytest.mark.asyncio
async def test_db_service_create_epic(db_service):
    epic = await db_service.create_epic("Auth Rewrite", "blue")
    assert epic["title"] == "Auth Rewrite"
    assert epic["color"] == "blue"
    assert "id" in epic


@pytest.mark.asyncio
async def test_db_service_get_epics(db_service):
    await db_service.create_epic("Epic A", "red")
    await db_service.create_epic("Epic B", "green")
    epics = await db_service.get_epics()
    assert len(epics) == 2
    assert epics[0]["title"] == "Epic A"
    assert epics[1]["title"] == "Epic B"


@pytest.mark.asyncio
async def test_db_service_update_epic(db_service):
    epic = await db_service.create_epic("Old Title", "blue")
    updated = await db_service.update_epic(epic["id"], title="New Title", color="red")
    assert updated["title"] == "New Title"
    assert updated["color"] == "red"


@pytest.mark.asyncio
async def test_db_service_delete_epic(db_service):
    epic = await db_service.create_epic("Temp Epic", "blue")
    async with db_service.db.connect() as conn:
        await conn.execute(
            "INSERT INTO items (id, title, column_name, position, epic_id) VALUES (?, ?, ?, ?, ?)",
            ("item-del-1", "Test Item", "todo", 0, epic["id"]),
        )
        await conn.commit()

    deleted = await db_service.delete_epic(epic["id"])
    assert deleted["id"] == epic["id"]

    async with db_service.db.connect() as conn:
        cursor = await conn.execute("SELECT epic_id FROM items WHERE id = ?", ("item-del-1",))
        row = await cursor.fetchone()
    assert row[0] is None


@pytest.mark.asyncio
async def test_db_service_get_epic_progress(db_service):
    epic = await db_service.create_epic("Progress Epic", "blue")
    async with db_service.db.connect() as conn:
        await conn.execute(
            "INSERT INTO items (id, title, column_name, position, epic_id) VALUES (?, ?, ?, ?, ?)",
            ("item-p1", "Todo Item", "todo", 0, epic["id"]),
        )
        await conn.execute(
            "INSERT INTO items (id, title, column_name, position, epic_id) VALUES (?, ?, ?, ?, ?)",
            ("item-p2", "Done Item", "done", 0, epic["id"]),
        )
        await conn.commit()

    progress = await db_service.get_epic_progress()
    assert epic["id"] in progress
    assert progress[epic["id"]]["todo"] == 1
    assert progress[epic["id"]]["done"] == 1
    assert progress[epic["id"]]["total"] == 2
