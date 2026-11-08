"""Tests for migration 029 — adds agent_config.enabled_skills."""

import pytest
import pytest_asyncio

from tests.unit.migrations.migration_helpers import load_migration, scratch_db, columns_of


def _load_migration_029():
    return load_migration("029_add_enabled_skills.py", "AddEnabledSkillsMigration")


@pytest_asyncio.fixture
async def config_db():
    async with scratch_db(
        "CREATE TABLE agent_config (id INTEGER PRIMARY KEY, model TEXT)",
        "INSERT INTO agent_config (id, model) VALUES (1, 'x')",
    ) as conn:
        yield conn


@pytest.mark.unit
class TestMigration029:
    async def test_up_adds_column(self, config_db):
        assert "enabled_skills" not in await columns_of(config_db, "agent_config")
        await _load_migration_029().up(config_db)
        assert "enabled_skills" in await columns_of(config_db, "agent_config")

    async def test_default_is_empty_list(self, config_db):
        await _load_migration_029().up(config_db)
        cur = await config_db.execute("SELECT enabled_skills FROM agent_config WHERE id = 1")
        assert (await cur.fetchone())["enabled_skills"] == "[]"

    async def test_down_is_noop(self, config_db):
        m = _load_migration_029()
        await m.up(config_db)
        await m.down(config_db)
        assert "enabled_skills" in await columns_of(config_db, "agent_config")
