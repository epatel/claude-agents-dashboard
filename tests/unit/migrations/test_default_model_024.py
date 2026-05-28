"""
Unit tests for the Opus 4.8 default-model change.

Covers:
- The centralized constants pin claude-opus-4-8 as the default and list it.
- Migration 024 bumps items / agent_config rows off the previous default
  (claude-opus-4-7) to the new default, leaves other models alone, and reverts.
"""

import importlib.util
import tempfile
from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio

from src.constants import AVAILABLE_MODELS, DEFAULT_MODEL

OLD_DEFAULT = "claude-opus-4-7"
NEW_DEFAULT = "claude-opus-4-8"


def _load_migration_024():
    """Import the real migration 024 module by file path and return its instance."""
    versions = Path(__file__).resolve().parents[3] / "src" / "migrations" / "versions"
    path = versions / "024_update_default_model_to_opus_4_8.py"
    spec = importlib.util.spec_from_file_location("migration_024", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.UpdateDefaultModelToOpus48Migration()


@pytest.mark.unit
class TestOpus48Constants:
    """The default model points at Opus 4.8 and it is offered in the picker."""

    def test_default_model_is_opus_4_8(self):
        assert DEFAULT_MODEL == NEW_DEFAULT

    def test_opus_4_8_is_available(self):
        ids = [m[0] for m in AVAILABLE_MODELS]
        assert NEW_DEFAULT in ids


@pytest_asyncio.fixture
async def seeded_db():
    """A db with items / agent_config seeded across several models."""
    with tempfile.TemporaryDirectory() as tmp:
        conn = await aiosqlite.connect(str(Path(tmp) / "test.db"))
        conn.row_factory = aiosqlite.Row
        await conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, model TEXT)")
        await conn.execute("CREATE TABLE agent_config (id INTEGER PRIMARY KEY, model TEXT)")
        # id 1: on the old default (should move). id 2: an explicit other model (untouched).
        await conn.execute("INSERT INTO items (id, model) VALUES (1, ?)", (OLD_DEFAULT,))
        await conn.execute("INSERT INTO items (id, model) VALUES (2, 'claude-sonnet-4-6')")
        await conn.execute("INSERT INTO agent_config (id, model) VALUES (1, ?)", (OLD_DEFAULT,))
        await conn.execute("INSERT INTO agent_config (id, model) VALUES (2, 'claude-haiku-4-5-20251001')")
        await conn.commit()
        yield conn
        await conn.close()


async def _model(db, table, row_id):
    cur = await db.execute(f"SELECT model FROM {table} WHERE id = ?", (row_id,))
    return (await cur.fetchone())["model"]


@pytest.mark.unit
class TestMigration024:
    """Migration 024 moves old-default rows forward and reverts cleanly."""

    async def test_up_bumps_old_default_only(self, seeded_db):
        await _load_migration_024().up(seeded_db)
        assert await _model(seeded_db, "items", 1) == NEW_DEFAULT
        assert await _model(seeded_db, "agent_config", 1) == NEW_DEFAULT
        # Explicit non-default choices are left alone.
        assert await _model(seeded_db, "items", 2) == "claude-sonnet-4-6"
        assert await _model(seeded_db, "agent_config", 2) == "claude-haiku-4-5-20251001"

    async def test_down_reverts(self, seeded_db):
        migration = _load_migration_024()
        await migration.up(seeded_db)
        await migration.down(seeded_db)
        assert await _model(seeded_db, "items", 1) == OLD_DEFAULT
        assert await _model(seeded_db, "agent_config", 1) == OLD_DEFAULT
        # Untouched rows stay untouched.
        assert await _model(seeded_db, "items", 2) == "claude-sonnet-4-6"
