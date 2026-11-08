"""Tests for migration 030 — adds agent_config.ollama_load_claude_md."""

import pytest
import pytest_asyncio

from tests.unit.migrations.migration_helpers import load_migration, scratch_db, columns_of


def _load_migration_030():
    return load_migration("030_add_ollama_load_claude_md.py", "AddOllamaLoadClaudeMdMigration")


@pytest_asyncio.fixture
async def config_db():
    async with scratch_db(
        "CREATE TABLE agent_config (id INTEGER PRIMARY KEY, model TEXT)",
        "INSERT INTO agent_config (id, model) VALUES (1, 'x')",
    ) as conn:
        yield conn


@pytest.mark.unit
class TestMigration030:
    async def test_up_adds_column(self, config_db):
        assert "ollama_load_claude_md" not in await columns_of(config_db, "agent_config")
        await _load_migration_030().up(config_db)
        assert "ollama_load_claude_md" in await columns_of(config_db, "agent_config")

    async def test_default_is_off(self, config_db):
        await _load_migration_030().up(config_db)
        cur = await config_db.execute(
            "SELECT ollama_load_claude_md FROM agent_config WHERE id = 1"
        )
        assert (await cur.fetchone())["ollama_load_claude_md"] == 0

    async def test_down_is_noop(self, config_db):
        m = _load_migration_030()
        await m.up(config_db)
        await m.down(config_db)
        assert "ollama_load_claude_md" in await columns_of(config_db, "agent_config")
