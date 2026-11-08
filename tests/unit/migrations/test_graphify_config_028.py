"""Tests for migration 028 — adds graphify config columns to agent_config."""

import pytest
import pytest_asyncio

from tests.unit.migrations.migration_helpers import load_migration, scratch_db, columns_of


def _load_migration_028():
    """Import the real migration 028 module by file path and return its instance."""
    return load_migration("028_add_graphify_config.py", "AddGraphifyConfigMigration")


@pytest_asyncio.fixture
async def config_db():
    """A db with a minimal agent_config table (no graphify columns yet)."""
    async with scratch_db(
        "CREATE TABLE agent_config (id INTEGER PRIMARY KEY, model TEXT)",
        "INSERT INTO agent_config (id, model) VALUES (1, 'x')",
    ) as conn:
        yield conn


@pytest.mark.unit
class TestMigration028:
    """Migration 028 adds graphify_enabled / graphify_auto_refresh / graphify_backend."""

    async def test_up_adds_columns(self, config_db):
        cols = await columns_of(config_db, "agent_config")
        assert "graphify_enabled" not in cols
        await _load_migration_028().up(config_db)
        cols = await columns_of(config_db, "agent_config")
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
        assert "graphify_enabled" in await columns_of(config_db, "agent_config")
