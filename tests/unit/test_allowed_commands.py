"""Tests for the allowed_commands migration (003)."""

import pytest
import aiosqlite


class TestAllowedCommandsMigration:
    async def test_migration_adds_column(self, test_db):
        """Verify allowed_commands column exists with default value."""
        async with test_db.connect() as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT allowed_commands FROM agent_config")
            row = await cursor.fetchone()
            assert row["allowed_commands"] == "[]"
