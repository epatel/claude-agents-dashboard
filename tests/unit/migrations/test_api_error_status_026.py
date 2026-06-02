"""Tests for migration 026 — adds api_error_status to token_usage."""

import importlib.util
import tempfile
from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio


def _load_migration_026():
    """Import the real migration 026 module by file path and return its instance."""
    versions = Path(__file__).resolve().parents[3] / "src" / "migrations" / "versions"
    path = versions / "026_add_api_error_status_to_token_usage.py"
    spec = importlib.util.spec_from_file_location("migration_026", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.AddApiErrorStatusToTokenUsageMigration()


@pytest_asyncio.fixture
async def token_usage_db():
    """A db with a minimal token_usage table (no api_error_status column yet)."""
    with tempfile.TemporaryDirectory() as tmp:
        conn = await aiosqlite.connect(str(Path(tmp) / "test.db"))
        conn.row_factory = aiosqlite.Row
        await conn.execute(
            "CREATE TABLE token_usage ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT, session_id TEXT, "
            "input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER, cost_usd REAL)"
        )
        await conn.execute(
            "INSERT INTO token_usage (item_id, total_tokens) VALUES ('i1', 100)"
        )
        await conn.commit()
        yield conn
        await conn.close()


async def _columns(db):
    cur = await db.execute("PRAGMA table_info(token_usage)")
    return {row["name"] for row in await cur.fetchall()}


@pytest.mark.unit
class TestMigration026:
    """Migration 026 adds a nullable api_error_status column."""

    async def test_up_adds_column(self, token_usage_db):
        assert "api_error_status" not in await _columns(token_usage_db)
        await _load_migration_026().up(token_usage_db)
        assert "api_error_status" in await _columns(token_usage_db)

    async def test_existing_rows_default_null(self, token_usage_db):
        await _load_migration_026().up(token_usage_db)
        cur = await token_usage_db.execute(
            "SELECT api_error_status FROM token_usage WHERE item_id = 'i1'"
        )
        assert (await cur.fetchone())["api_error_status"] is None

    async def test_column_persists_value(self, token_usage_db):
        await _load_migration_026().up(token_usage_db)
        await token_usage_db.execute(
            "INSERT INTO token_usage (item_id, api_error_status) VALUES ('i2', 529)"
        )
        await token_usage_db.commit()
        cur = await token_usage_db.execute(
            "SELECT api_error_status FROM token_usage WHERE item_id = 'i2'"
        )
        assert (await cur.fetchone())["api_error_status"] == 529

    async def test_down_is_noop(self, token_usage_db):
        migration = _load_migration_026()
        await migration.up(token_usage_db)
        # down() leaves the column in place (matches other column-add migrations).
        await migration.down(token_usage_db)
        assert "api_error_status" in await _columns(token_usage_db)
