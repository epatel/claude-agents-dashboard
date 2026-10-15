"""
Unit tests for migration 032 (strip redundant [1m] from natively-1M Opus models).

Covers:
- The constants no longer offer [1m] variants for Opus 4.7+, but keep the
  opt-in ones (Opus 4.6, Sonnet 4.6).
- Migration 032 rewrites claude-opus-5 / 4-8 / 4-7 "[1m]" rows to the bare id
  in items and agent_config, leaves the opt-in [1m] rows alone, and its down()
  is a no-op.
"""

import importlib.util
import tempfile
from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio

from src.constants import AVAILABLE_MODELS


def _load_migration_032():
    """Import the real migration 032 module by file path and return its instance."""
    versions = Path(__file__).resolve().parents[3] / "src" / "migrations" / "versions"
    path = versions / "032_strip_redundant_1m_suffix.py"
    spec = importlib.util.spec_from_file_location("migration_032", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.StripRedundant1MSuffixMigration()


@pytest.mark.unit
class TestNative1MConstants:
    """Only the opt-in models keep a [1m] picker entry."""

    def test_no_redundant_1m_variants(self):
        ids = [m[0] for m in AVAILABLE_MODELS]
        for model in ("claude-opus-5", "claude-opus-4-8", "claude-opus-4-7"):
            assert model in ids
            assert f"{model}[1m]" not in ids

    def test_opt_in_1m_variants_kept(self):
        ids = [m[0] for m in AVAILABLE_MODELS]
        assert "claude-opus-4-6[1m]" in ids
        assert "claude-sonnet-4-6[1m]" in ids


@pytest_asyncio.fixture
async def seeded_db():
    """A db with items / agent_config seeded with [1m] and plain models."""
    with tempfile.TemporaryDirectory() as tmp:
        conn = await aiosqlite.connect(str(Path(tmp) / "test.db"))
        conn.row_factory = aiosqlite.Row
        await conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, model TEXT)")
        await conn.execute("CREATE TABLE agent_config (id INTEGER PRIMARY KEY, model TEXT)")
        rows = [
            (1, "claude-opus-5[1m]"),
            (2, "claude-opus-4-8[1m]"),
            (3, "claude-opus-4-7[1m]"),
            (4, "claude-opus-4-6[1m]"),
            (5, "claude-sonnet-4-6[1m]"),
            (6, "claude-opus-5"),
        ]
        await conn.executemany("INSERT INTO items (id, model) VALUES (?, ?)", rows)
        await conn.execute("INSERT INTO agent_config (id, model) VALUES (1, 'claude-opus-5[1m]')")
        await conn.commit()
        yield conn
        await conn.close()


async def _model(db, table, row_id):
    cur = await db.execute(f"SELECT model FROM {table} WHERE id = ?", (row_id,))
    return (await cur.fetchone())["model"]


@pytest.mark.unit
class TestMigration032:
    """Migration 032 strips [1m] only where it has no effect."""

    async def test_up_strips_native_1m_models(self, seeded_db):
        await _load_migration_032().up(seeded_db)
        assert await _model(seeded_db, "items", 1) == "claude-opus-5"
        assert await _model(seeded_db, "items", 2) == "claude-opus-4-8"
        assert await _model(seeded_db, "items", 3) == "claude-opus-4-7"
        assert await _model(seeded_db, "agent_config", 1) == "claude-opus-5"

    async def test_up_keeps_opt_in_models(self, seeded_db):
        await _load_migration_032().up(seeded_db)
        assert await _model(seeded_db, "items", 4) == "claude-opus-4-6[1m]"
        assert await _model(seeded_db, "items", 5) == "claude-sonnet-4-6[1m]"
        assert await _model(seeded_db, "items", 6) == "claude-opus-5"

    async def test_down_is_noop(self, seeded_db):
        migration = _load_migration_032()
        await migration.up(seeded_db)
        await migration.down(seeded_db)
        assert await _model(seeded_db, "items", 1) == "claude-opus-5"
        assert await _model(seeded_db, "items", 4) == "claude-opus-4-6[1m]"
