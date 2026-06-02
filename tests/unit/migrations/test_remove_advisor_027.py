"""Tests for migration 027 — strips the removed +advisor suffix from models."""

import importlib.util
import tempfile
from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio


def _load_migration_027():
    versions = Path(__file__).resolve().parents[3] / "src" / "migrations" / "versions"
    path = versions / "027_remove_advisor_model.py"
    spec = importlib.util.spec_from_file_location("migration_027", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.RemoveAdvisorModelMigration()


@pytest_asyncio.fixture
async def models_db():
    """A db with items + agent_config carrying assorted model strings."""
    with tempfile.TemporaryDirectory() as tmp:
        conn = await aiosqlite.connect(str(Path(tmp) / "test.db"))
        conn.row_factory = aiosqlite.Row
        await conn.execute("CREATE TABLE items (id TEXT PRIMARY KEY, model TEXT)")
        await conn.execute("CREATE TABLE agent_config (id INTEGER PRIMARY KEY, model TEXT)")
        await conn.execute("INSERT INTO items (id, model) VALUES ('i1', 'claude-sonnet-4-6+advisor')")
        await conn.execute("INSERT INTO items (id, model) VALUES ('i2', 'claude-opus-4-8')")
        await conn.execute("INSERT INTO items (id, model) VALUES ('i3', NULL)")
        await conn.execute("INSERT INTO agent_config (id, model) VALUES (1, 'claude-sonnet-4-6+advisor')")
        await conn.commit()
        yield conn
        await conn.close()


async def _model(db, table, key_col, key):
    cur = await db.execute(f"SELECT model FROM {table} WHERE {key_col} = ?", (key,))
    return (await cur.fetchone())["model"]


@pytest.mark.unit
class TestMigration027:
    async def test_strips_suffix_from_items(self, models_db):
        await _load_migration_027().up(models_db)
        assert await _model(models_db, "items", "id", "i1") == "claude-sonnet-4-6"

    async def test_strips_suffix_from_agent_config(self, models_db):
        await _load_migration_027().up(models_db)
        assert await _model(models_db, "agent_config", "id", 1) == "claude-sonnet-4-6"

    async def test_leaves_other_models_untouched(self, models_db):
        await _load_migration_027().up(models_db)
        assert await _model(models_db, "items", "id", "i2") == "claude-opus-4-8"

    async def test_handles_null_model(self, models_db):
        await _load_migration_027().up(models_db)
        assert await _model(models_db, "items", "id", "i3") is None

    async def test_down_is_noop(self, models_db):
        migration = _load_migration_027()
        await migration.up(models_db)
        await migration.down(models_db)
        # Suffix stays stripped — removal is irreversible.
        assert await _model(models_db, "items", "id", "i1") == "claude-sonnet-4-6"
