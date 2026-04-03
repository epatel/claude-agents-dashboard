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


# --- Edge cases and expanded coverage ---


@pytest.mark.asyncio
async def test_db_service_delete_nonexistent_epic(db_service):
    """Deleting a non-existent epic returns None."""
    result = await db_service.delete_epic("does-not-exist")
    assert result is None


@pytest.mark.asyncio
async def test_db_service_update_nonexistent_epic(db_service):
    """Updating a non-existent epic returns None."""
    result = await db_service.update_epic("does-not-exist", title="X")
    assert result is None


@pytest.mark.asyncio
async def test_db_service_create_todo_item_with_epic(db_service):
    """create_todo_item persists epic_id on the new item."""
    epic = await db_service.create_epic("My Epic", "green")
    item = await db_service.create_todo_item("Task A", "Do something", epic["id"])
    assert item["epic_id"] == epic["id"]
    assert item["column_name"] == "todo"


@pytest.mark.asyncio
async def test_db_service_create_todo_item_without_epic(db_service):
    """create_todo_item with no epic_id sets it to None."""
    item = await db_service.create_todo_item("Task B", "Do something else")
    assert item["epic_id"] is None


@pytest.mark.asyncio
async def test_db_service_epic_progress_excludes_archive_from_total(db_service):
    """Archived items count under 'archive' but not in 'total'."""
    epic = await db_service.create_epic("Archive Test", "red")
    async with db_service.db.connect() as conn:
        await conn.execute(
            "INSERT INTO items (id, title, column_name, position, epic_id) VALUES (?, ?, ?, ?, ?)",
            ("item-a1", "Active", "doing", 0, epic["id"]),
        )
        await conn.execute(
            "INSERT INTO items (id, title, column_name, position, epic_id) VALUES (?, ?, ?, ?, ?)",
            ("item-a2", "Archived", "archive", 0, epic["id"]),
        )
        await conn.commit()

    progress = await db_service.get_epic_progress()
    p = progress[epic["id"]]
    assert p["doing"] == 1
    assert p["archive"] == 1
    assert p["total"] == 1  # archive excluded from total


@pytest.mark.asyncio
async def test_db_service_epic_progress_all_columns(db_service):
    """Progress tracks items across all six columns."""
    epic = await db_service.create_epic("Full Coverage", "purple")
    columns = ["todo", "doing", "questions", "review", "done", "archive"]
    async with db_service.db.connect() as conn:
        for i, col in enumerate(columns):
            await conn.execute(
                "INSERT INTO items (id, title, column_name, position, epic_id) VALUES (?, ?, ?, ?, ?)",
                (f"item-fc-{i}", f"Item {col}", col, 0, epic["id"]),
            )
        await conn.commit()

    progress = await db_service.get_epic_progress()
    p = progress[epic["id"]]
    for col in columns:
        assert p[col] == 1, f"Expected 1 item in {col}"
    assert p["total"] == 5  # 6 items minus 1 archive


@pytest.mark.asyncio
async def test_db_service_epic_progress_empty_epic(db_service):
    """An epic with no items doesn't appear in progress."""
    await db_service.create_epic("Empty Epic", "teal")
    progress = await db_service.get_epic_progress()
    # Empty epic has no items, so it won't appear in progress dict
    assert len(progress) == 0


@pytest.mark.asyncio
async def test_db_service_delete_epic_with_items_in_multiple_columns(db_service):
    """Deleting an epic nullifies epic_id on items in all columns."""
    epic = await db_service.create_epic("Multi-Col Epic", "orange")
    async with db_service.db.connect() as conn:
        await conn.execute(
            "INSERT INTO items (id, title, column_name, position, epic_id) VALUES (?, ?, ?, ?, ?)",
            ("item-mc1", "Todo", "todo", 0, epic["id"]),
        )
        await conn.execute(
            "INSERT INTO items (id, title, column_name, position, epic_id) VALUES (?, ?, ?, ?, ?)",
            ("item-mc2", "Doing", "doing", 0, epic["id"]),
        )
        await conn.execute(
            "INSERT INTO items (id, title, column_name, position, epic_id) VALUES (?, ?, ?, ?, ?)",
            ("item-mc3", "Done", "done", 0, epic["id"]),
        )
        await conn.commit()

    await db_service.delete_epic(epic["id"])

    async with db_service.db.connect() as conn:
        cursor = await conn.execute(
            "SELECT id, epic_id FROM items WHERE id IN ('item-mc1', 'item-mc2', 'item-mc3')"
        )
        rows = await cursor.fetchall()
    for row in rows:
        assert row[1] is None, f"Item {row[0]} should have epic_id=None"


@pytest.mark.asyncio
async def test_db_service_epic_auto_position(db_service):
    """Epics get auto-incrementing positions."""
    e1 = await db_service.create_epic("First", "red")
    e2 = await db_service.create_epic("Second", "blue")
    e3 = await db_service.create_epic("Third", "green")
    assert e1["position"] == 0
    assert e2["position"] == 1
    assert e3["position"] == 2
