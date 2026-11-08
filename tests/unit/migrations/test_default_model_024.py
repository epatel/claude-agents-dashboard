"""
Unit tests for the Opus 4.8 default-model change.

Covers:
- claude-opus-4-8 stays selectable in the centralized constants (it is no longer
  the default — see test_default_model_031.py).
- Migration 024 bumps items / agent_config rows off the previous default
  (claude-opus-4-7) to the new default, leaves other models alone, and reverts.
"""

import pytest
import pytest_asyncio

from src.constants import AVAILABLE_MODELS
from tests.unit.migrations.migration_helpers import load_migration, scratch_db, model_of

OLD_DEFAULT = "claude-opus-4-7"
NEW_DEFAULT = "claude-opus-4-8"


def _load_migration_024():
    """Import the real migration 024 module by file path and return its instance."""
    return load_migration("024_update_default_model_to_opus_4_8.py", "UpdateDefaultModelToOpus48Migration")


@pytest.mark.unit
class TestOpus48Constants:
    """Opus 4.8 is still offered in the picker (the default moved on to Opus 5)."""

    def test_opus_4_8_is_available(self):
        ids = [m[0] for m in AVAILABLE_MODELS]
        assert NEW_DEFAULT in ids


@pytest_asyncio.fixture
async def seeded_db():
    """A db with items / agent_config seeded across several models."""
    async with scratch_db(
        "CREATE TABLE items (id INTEGER PRIMARY KEY, model TEXT)",
        "CREATE TABLE agent_config (id INTEGER PRIMARY KEY, model TEXT)",
        # id 1: on the old default (should move). id 2: an explicit other model (untouched).
        ("INSERT INTO items (id, model) VALUES (1, ?)", (OLD_DEFAULT,)),
        "INSERT INTO items (id, model) VALUES (2, 'claude-sonnet-4-6')",
        ("INSERT INTO agent_config (id, model) VALUES (1, ?)", (OLD_DEFAULT,)),
        "INSERT INTO agent_config (id, model) VALUES (2, 'claude-haiku-4-5-20251001')",
    ) as conn:
        yield conn


@pytest.mark.unit
class TestMigration024:
    """Migration 024 moves old-default rows forward and reverts cleanly."""

    async def test_up_bumps_old_default_only(self, seeded_db):
        await _load_migration_024().up(seeded_db)
        assert await model_of(seeded_db, "items", 1) == NEW_DEFAULT
        assert await model_of(seeded_db, "agent_config", 1) == NEW_DEFAULT
        # Explicit non-default choices are left alone.
        assert await model_of(seeded_db, "items", 2) == "claude-sonnet-4-6"
        assert await model_of(seeded_db, "agent_config", 2) == "claude-haiku-4-5-20251001"

    async def test_down_reverts(self, seeded_db):
        migration = _load_migration_024()
        await migration.up(seeded_db)
        await migration.down(seeded_db)
        assert await model_of(seeded_db, "items", 1) == OLD_DEFAULT
        assert await model_of(seeded_db, "agent_config", 1) == OLD_DEFAULT
        # Untouched rows stay untouched.
        assert await model_of(seeded_db, "items", 2) == "claude-sonnet-4-6"
