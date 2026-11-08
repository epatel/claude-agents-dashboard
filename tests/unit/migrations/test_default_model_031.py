"""
Unit tests for the Opus 5 default-model change.

Covers:
- The centralized constants pin claude-opus-5 as the default and list it
  (alongside Sonnet 5). Its "[1m]" variant is gone — see migration 032.
- Migration 031 bumps items / agent_config rows off the previous default
  (claude-opus-4-8, plus its [1m] variant) to the new default, leaves other
  models alone, and reverts.
"""

import pytest
import pytest_asyncio

from src.constants import AVAILABLE_MODELS, DEFAULT_MODEL
from tests.unit.migrations.migration_helpers import load_migration, scratch_db, model_of

OLD_DEFAULT = "claude-opus-4-8"
NEW_DEFAULT = "claude-opus-5"


def _load_migration_031():
    """Import the real migration 031 module by file path and return its instance."""
    return load_migration("031_update_default_model_to_opus_5.py", "UpdateDefaultModelToOpus5Migration")


@pytest.mark.unit
class TestOpus5Constants:
    """The default model points at Opus 5 and the new models are offered."""

    def test_default_model_is_opus_5(self):
        assert DEFAULT_MODEL == NEW_DEFAULT

    def test_new_models_are_available(self):
        ids = [m[0] for m in AVAILABLE_MODELS]
        assert NEW_DEFAULT in ids
        assert "claude-sonnet-5" in ids

    def test_previous_default_stays_selectable(self):
        ids = [m[0] for m in AVAILABLE_MODELS]
        assert OLD_DEFAULT in ids


@pytest_asyncio.fixture
async def seeded_db():
    """A db with items / agent_config seeded across several models."""
    async with scratch_db(
        "CREATE TABLE items (id INTEGER PRIMARY KEY, model TEXT)",
        "CREATE TABLE agent_config (id INTEGER PRIMARY KEY, model TEXT)",
        # id 1: old default (moves). id 2: explicit other model (untouched).
        # id 3: old default's 1M variant (moves to the new 1M variant).
        ("INSERT INTO items (id, model) VALUES (1, ?)", (OLD_DEFAULT,)),
        "INSERT INTO items (id, model) VALUES (2, 'claude-sonnet-4-6')",
        "INSERT INTO items (id, model) VALUES (3, 'claude-opus-4-8[1m]')",
        ("INSERT INTO agent_config (id, model) VALUES (1, ?)", (OLD_DEFAULT,)),
        "INSERT INTO agent_config (id, model) VALUES (2, 'claude-haiku-4-5-20251001')",
    ) as conn:
        yield conn


@pytest.mark.unit
class TestMigration031:
    """Migration 031 moves old-default rows forward and reverts cleanly."""

    async def test_up_bumps_old_default_only(self, seeded_db):
        await _load_migration_031().up(seeded_db)
        assert await model_of(seeded_db, "items", 1) == NEW_DEFAULT
        assert await model_of(seeded_db, "agent_config", 1) == NEW_DEFAULT
        # The 1M opt-in is preserved across the bump.
        assert await model_of(seeded_db, "items", 3) == "claude-opus-5[1m]"
        # Explicit non-default choices are left alone.
        assert await model_of(seeded_db, "items", 2) == "claude-sonnet-4-6"
        assert await model_of(seeded_db, "agent_config", 2) == "claude-haiku-4-5-20251001"

    async def test_down_reverts(self, seeded_db):
        migration = _load_migration_031()
        await migration.up(seeded_db)
        await migration.down(seeded_db)
        assert await model_of(seeded_db, "items", 1) == OLD_DEFAULT
        assert await model_of(seeded_db, "agent_config", 1) == OLD_DEFAULT
        assert await model_of(seeded_db, "items", 3) == "claude-opus-4-8[1m]"
        # Untouched rows stay untouched.
        assert await model_of(seeded_db, "items", 2) == "claude-sonnet-4-6"
