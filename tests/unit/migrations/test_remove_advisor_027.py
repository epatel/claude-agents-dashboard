"""Tests for migration 027 — strips the removed +advisor suffix from models."""

import pytest
import pytest_asyncio

from tests.unit.migrations.migration_helpers import load_migration, scratch_db, model_of


def _load_migration_027():
    return load_migration("027_remove_advisor_model.py", "RemoveAdvisorModelMigration")


@pytest_asyncio.fixture
async def models_db():
    """A db with items + agent_config carrying assorted model strings."""
    async with scratch_db(
        "CREATE TABLE items (id TEXT PRIMARY KEY, model TEXT)",
        "CREATE TABLE agent_config (id INTEGER PRIMARY KEY, model TEXT)",
        "INSERT INTO items (id, model) VALUES ('i1', 'claude-sonnet-4-6+advisor')",
        "INSERT INTO items (id, model) VALUES ('i2', 'claude-opus-4-8')",
        "INSERT INTO items (id, model) VALUES ('i3', NULL)",
        "INSERT INTO agent_config (id, model) VALUES (1, 'claude-sonnet-4-6+advisor')",
    ) as conn:
        yield conn


@pytest.mark.unit
class TestMigration027:
    async def test_strips_suffix_from_items(self, models_db):
        await _load_migration_027().up(models_db)
        assert await model_of(models_db, "items", "i1") == "claude-sonnet-4-6"

    async def test_strips_suffix_from_agent_config(self, models_db):
        await _load_migration_027().up(models_db)
        assert await model_of(models_db, "agent_config", 1) == "claude-sonnet-4-6"

    async def test_leaves_other_models_untouched(self, models_db):
        await _load_migration_027().up(models_db)
        assert await model_of(models_db, "items", "i2") == "claude-opus-4-8"

    async def test_handles_null_model(self, models_db):
        await _load_migration_027().up(models_db)
        assert await model_of(models_db, "items", "i3") is None

    async def test_down_is_noop(self, models_db):
        migration = _load_migration_027()
        await migration.up(models_db)
        await migration.down(models_db)
        # Suffix stays stripped — removal is irreversible.
        assert await model_of(models_db, "items", "i1") == "claude-sonnet-4-6"
