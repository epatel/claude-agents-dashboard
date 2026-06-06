"""Tests for migration 029 — adds agent_config.enabled_skills."""

import importlib.util
import tempfile
from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio


def _load_migration_029():
    versions = Path(__file__).resolve().parents[3] / "src" / "migrations" / "versions"
    path = versions / "029_add_enabled_skills.py"
    spec = importlib.util.spec_from_file_location("migration_029", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.AddEnabledSkillsMigration()


@pytest_asyncio.fixture
async def config_db():
    with tempfile.TemporaryDirectory() as tmp:
        conn = await aiosqlite.connect(str(Path(tmp) / "test.db"))
        conn.row_factory = aiosqlite.Row
        await conn.execute("CREATE TABLE agent_config (id INTEGER PRIMARY KEY, model TEXT)")
        await conn.execute("INSERT INTO agent_config (id, model) VALUES (1, 'x')")
        await conn.commit()
        yield conn
        await conn.close()


async def _columns(db):
    cur = await db.execute("PRAGMA table_info(agent_config)")
    return {row["name"] for row in await cur.fetchall()}


@pytest.mark.unit
class TestMigration029:
    async def test_up_adds_column(self, config_db):
        assert "enabled_skills" not in await _columns(config_db)
        await _load_migration_029().up(config_db)
        assert "enabled_skills" in await _columns(config_db)

    async def test_default_is_empty_list(self, config_db):
        await _load_migration_029().up(config_db)
        cur = await config_db.execute("SELECT enabled_skills FROM agent_config WHERE id = 1")
        assert (await cur.fetchone())["enabled_skills"] == "[]"

    async def test_down_is_noop(self, config_db):
        m = _load_migration_029()
        await m.up(config_db)
        await m.down(config_db)
        assert "enabled_skills" in await _columns(config_db)
