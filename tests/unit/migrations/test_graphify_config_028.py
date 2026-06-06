"""Tests for migration 028 — adds graphify config columns to agent_config."""

import importlib.util
import tempfile
from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio


def _load_migration_028():
    """Import the real migration 028 module by file path and return its instance."""
    versions = Path(__file__).resolve().parents[3] / "src" / "migrations" / "versions"
    path = versions / "028_add_graphify_config.py"
    spec = importlib.util.spec_from_file_location("migration_028", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.AddGraphifyConfigMigration()


@pytest_asyncio.fixture
async def config_db():
    """A db with a minimal agent_config table (no graphify columns yet)."""
    with tempfile.TemporaryDirectory() as tmp:
        conn = await aiosqlite.connect(str(Path(tmp) / "test.db"))
        conn.row_factory = aiosqlite.Row
        await conn.execute(
            "CREATE TABLE agent_config (id INTEGER PRIMARY KEY, model TEXT)"
        )
        await conn.execute("INSERT INTO agent_config (id, model) VALUES (1, 'x')")
        await conn.commit()
        yield conn
        await conn.close()


async def _columns(db):
    cur = await db.execute("PRAGMA table_info(agent_config)")
    return {row["name"] for row in await cur.fetchall()}


@pytest.mark.unit
class TestMigration028:
    """Migration 028 adds graphify_enabled / graphify_auto_refresh / graphify_backend."""

    async def test_up_adds_columns(self, config_db):
        cols = await _columns(config_db)
        assert "graphify_enabled" not in cols
        await _load_migration_028().up(config_db)
        cols = await _columns(config_db)
        assert {"graphify_enabled", "graphify_auto_refresh", "graphify_backend"} <= cols

    async def test_defaults(self, config_db):
        await _load_migration_028().up(config_db)
        cur = await config_db.execute(
            "SELECT graphify_enabled, graphify_auto_refresh, graphify_backend "
            "FROM agent_config WHERE id = 1"
        )
        row = await cur.fetchone()
        assert row["graphify_enabled"] == 0
        assert row["graphify_auto_refresh"] == 1
        assert row["graphify_backend"] == "ast"

    async def test_down_is_noop(self, config_db):
        migration = _load_migration_028()
        await migration.up(config_db)
        await migration.down(config_db)
        assert "graphify_enabled" in await _columns(config_db)
