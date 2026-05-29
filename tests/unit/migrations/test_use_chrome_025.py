"""Tests for migration 025 — adds the per-item use_chrome column."""

import importlib.util
import tempfile
from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio


def _load_migration_025():
    """Import the real migration 025 module by file path and return its instance."""
    versions = Path(__file__).resolve().parents[3] / "src" / "migrations" / "versions"
    path = versions / "025_add_use_chrome_to_items.py"
    spec = importlib.util.spec_from_file_location("migration_025", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.AddUseChromeToItemsMigration()


@pytest_asyncio.fixture
async def items_db():
    """A db with a minimal items table (no use_chrome column yet)."""
    with tempfile.TemporaryDirectory() as tmp:
        conn = await aiosqlite.connect(str(Path(tmp) / "test.db"))
        conn.row_factory = aiosqlite.Row
        await conn.execute("CREATE TABLE items (id TEXT PRIMARY KEY, title TEXT)")
        await conn.execute("INSERT INTO items (id, title) VALUES ('i1', 'Task')")
        await conn.commit()
        yield conn
        await conn.close()


async def _columns(db):
    cur = await db.execute("PRAGMA table_info(items)")
    return {row["name"] for row in await cur.fetchall()}


@pytest.mark.unit
class TestMigration025:
    """Migration 025 adds use_chrome defaulting to 0."""

    async def test_up_adds_column(self, items_db):
        assert "use_chrome" not in await _columns(items_db)
        await _load_migration_025().up(items_db)
        assert "use_chrome" in await _columns(items_db)

    async def test_existing_rows_default_off(self, items_db):
        await _load_migration_025().up(items_db)
        cur = await items_db.execute("SELECT use_chrome FROM items WHERE id = 'i1'")
        assert (await cur.fetchone())["use_chrome"] == 0

    async def test_column_persists_value(self, items_db):
        await _load_migration_025().up(items_db)
        await items_db.execute(
            "INSERT INTO items (id, title, use_chrome) VALUES ('i2', 'Browse', 1)"
        )
        await items_db.commit()
        cur = await items_db.execute("SELECT use_chrome FROM items WHERE id = 'i2'")
        assert (await cur.fetchone())["use_chrome"] == 1

    async def test_down_is_noop(self, items_db):
        migration = _load_migration_025()
        await migration.up(items_db)
        # down() leaves the column in place (matches other column-add migrations).
        await migration.down(items_db)
        assert "use_chrome" in await _columns(items_db)
