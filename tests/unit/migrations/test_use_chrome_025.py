"""Tests for migration 025 — adds the per-item use_chrome column."""

import pytest
import pytest_asyncio

from tests.unit.migrations.migration_helpers import load_migration, scratch_db, columns_of


def _load_migration_025():
    """Import the real migration 025 module by file path and return its instance."""
    return load_migration("025_add_use_chrome_to_items.py", "AddUseChromeToItemsMigration")


@pytest_asyncio.fixture
async def items_db():
    """A db with a minimal items table (no use_chrome column yet)."""
    async with scratch_db(
        "CREATE TABLE items (id TEXT PRIMARY KEY, title TEXT)",
        "INSERT INTO items (id, title) VALUES ('i1', 'Task')",
    ) as conn:
        yield conn


@pytest.mark.unit
class TestMigration025:
    """Migration 025 adds use_chrome defaulting to 0."""

    async def test_up_adds_column(self, items_db):
        assert "use_chrome" not in await columns_of(items_db, "items")
        await _load_migration_025().up(items_db)
        assert "use_chrome" in await columns_of(items_db, "items")

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
        assert "use_chrome" in await columns_of(items_db, "items")
