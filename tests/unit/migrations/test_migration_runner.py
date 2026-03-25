"""
P0 Priority Unit Tests: Database Migration Up/Down Operations

Tests the core migration functionality including:
- Migration discovery and loading
- Up/down migration execution
- Migration state tracking
- Error handling and rollback
"""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock
import aiosqlite

from src.migrations.migration import Migration
from src.migrations.runner import MigrationRunner


class TestMigration001(Migration):
    """Test migration for unit testing."""

    def __init__(self):
        super().__init__("001", "Test migration for unit tests")

    async def up(self, db: aiosqlite.Connection) -> None:
        await db.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, name TEXT)")

    async def down(self, db: aiosqlite.Connection) -> None:
        await db.execute("DROP TABLE IF EXISTS test_table")


class TestMigration002(Migration):
    """Second test migration."""

    def __init__(self):
        super().__init__("002", "Second test migration")

    async def up(self, db: aiosqlite.Connection) -> None:
        await db.execute("ALTER TABLE test_table ADD COLUMN email TEXT")

    async def down(self, db: aiosqlite.Connection) -> None:
        await db.execute("ALTER TABLE test_table DROP COLUMN email")


class TestMigrationFailure(Migration):
    """Migration that fails for error testing."""

    def __init__(self):
        super().__init__("999", "Migration that fails")

    async def up(self, db: aiosqlite.Connection) -> None:
        # This will fail - invalid SQL
        await db.execute("INVALID SQL STATEMENT")

    async def down(self, db: aiosqlite.Connection) -> None:
        # This will also fail
        await db.execute("ANOTHER INVALID SQL")


@pytest.mark.unit
class TestMigrationRunner:
    """Test suite for MigrationRunner."""

    async def test_migration_table_creation(self, test_db_connection, migration_runner):
        """Test that migrations table is created correctly."""
        await migration_runner._ensure_migrations_table(test_db_connection)

        # Check table exists
        cursor = await test_db_connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        )
        result = await cursor.fetchone()
        assert result is not None

        # Check table structure
        cursor = await test_db_connection.execute("PRAGMA table_info(schema_migrations)")
        columns = await cursor.fetchall()
        column_names = [col[1] for col in columns]
        assert "version" in column_names
        assert "description" in column_names
        assert "applied_at" in column_names

    async def test_migration_discovery_empty_directory(self, temp_dir):
        """Test migration discovery with empty directory."""
        migrations_dir = temp_dir / "empty_migrations"
        migrations_dir.mkdir()
        runner = MigrationRunner(migrations_dir)

        await runner._discover_migrations()
        assert len(runner._migrations) == 0

    async def test_apply_single_migration(self, test_db_connection, migration_runner):
        """Test applying a single migration."""
        migration = TestMigration001()

        await migration_runner.apply_migration(test_db_connection, migration)

        # Check migration was applied
        cursor = await test_db_connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = ?", ("001",)
        )
        count = (await cursor.fetchone())[0]
        assert count == 1

        # Check table was created
        cursor = await test_db_connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='test_table'"
        )
        result = await cursor.fetchone()
        assert result is not None

    async def test_rollback_single_migration(self, test_db_connection, migration_runner):
        """Test rolling back a single migration."""
        migration = TestMigration001()

        # First apply the migration
        await migration_runner.apply_migration(test_db_connection, migration)

        # Then rollback
        await migration_runner.rollback_migration(test_db_connection, migration)

        # Check migration record was removed
        cursor = await test_db_connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = ?", ("001",)
        )
        count = (await cursor.fetchone())[0]
        assert count == 0

        # Check table was dropped
        cursor = await test_db_connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='test_table'"
        )
        result = await cursor.fetchone()
        assert result is None

    async def test_apply_multiple_migrations_up(self, test_db_connection, migration_runner):
        """Test applying multiple migrations in sequence."""
        # Add migrations to runner
        migration_runner._migrations = {
            "001": TestMigration001(),
            "002": TestMigration002()
        }
        migration_runner._discovered = True

        await migration_runner.migrate_up(test_db_connection)

        # Check both migrations were applied
        cursor = await test_db_connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )
        applied = [row[0] for row in await cursor.fetchall()]
        assert applied == ["001", "002"]

        # Check both schema changes were applied
        cursor = await test_db_connection.execute("PRAGMA table_info(test_table)")
        columns = await cursor.fetchall()
        column_names = [col[1] for col in columns]
        assert "id" in column_names
        assert "name" in column_names
        assert "email" in column_names

    async def test_rollback_multiple_migrations_down(self, test_db_connection, migration_runner):
        """Test rolling back multiple migrations."""
        # Add migrations to runner
        migration_runner._migrations = {
            "001": TestMigration001(),
            "002": TestMigration002()
        }
        migration_runner._discovered = True

        # First apply migrations
        await migration_runner.migrate_up(test_db_connection)

        # Then rollback to version 001
        await migration_runner.migrate_down(test_db_connection, "001")

        # Check only migration 001 remains
        cursor = await test_db_connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )
        applied = [row[0] for row in await cursor.fetchall()]
        assert applied == ["001"]

        # Check email column was removed
        cursor = await test_db_connection.execute("PRAGMA table_info(test_table)")
        columns = await cursor.fetchall()
        column_names = [col[1] for col in columns]
        assert "email" not in column_names

    async def test_migration_failure_handling(self, test_db_connection, migration_runner):
        """Test that failed migrations are handled correctly."""
        migration = TestMigrationFailure()

        with pytest.raises(Exception):
            await migration_runner.apply_migration(test_db_connection, migration)

        # Check migration was not recorded as applied
        cursor = await test_db_connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = ?", ("999",)
        )
        count = (await cursor.fetchone())[0]
        assert count == 0

    async def test_get_migration_status(self, test_db_connection, migration_runner):
        """Test getting migration status information."""
        # Add migrations to runner
        migration_runner._migrations = {
            "001": TestMigration001(),
            "002": TestMigration002()
        }
        migration_runner._discovered = True

        # Apply first migration only
        await migration_runner.apply_migration(test_db_connection, migration_runner._migrations["001"])

        status = await migration_runner.get_status(test_db_connection)

        assert status["total_migrations"] == 2
        assert status["applied_count"] == 1
        assert status["pending_count"] == 1
        assert status["applied_migrations"] == ["001"]
        assert status["pending_migrations"] == ["002"]
        assert status["latest_applied"] == "001"
        assert status["next_pending"] == "002"

    async def test_target_version_migration_up(self, test_db_connection, migration_runner):
        """Test migrating up to a specific target version."""
        # Add migrations to runner
        migration_runner._migrations = {
            "001": TestMigration001(),
            "002": TestMigration002()
        }
        migration_runner._discovered = True

        # Migrate up to version 001 only
        await migration_runner.migrate_up(test_db_connection, target_version="001")

        # Check only migration 001 was applied
        cursor = await test_db_connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )
        applied = [row[0] for row in await cursor.fetchall()]
        assert applied == ["001"]

    async def test_no_pending_migrations(self, test_db_connection, migration_runner):
        """Test behavior when no migrations are pending."""
        # Add migrations and apply them all
        migration_runner._migrations = {
            "001": TestMigration001(),
            "002": TestMigration002()
        }
        migration_runner._discovered = True

        await migration_runner.migrate_up(test_db_connection)

        # Try to migrate again - should be no-op
        await migration_runner.migrate_up(test_db_connection)

        # Still should have both migrations
        applied = await migration_runner.get_applied_migrations(test_db_connection)
        assert len(applied) == 2

    async def test_rollback_to_nonexistent_version(self, test_db_connection, migration_runner):
        """Test rollback behavior when target version doesn't exist."""
        migration_runner._migrations = {
            "001": TestMigration001(),
        }
        migration_runner._discovered = True

        await migration_runner.migrate_up(test_db_connection)

        # Try to rollback to version that doesn't exist - should be no-op
        await migration_runner.migrate_down(test_db_connection, "000")

        # Migration should still be applied
        applied = await migration_runner.get_applied_migrations(test_db_connection)
        assert applied == ["001"]


@pytest.mark.unit
class TestMigrationBase:
    """Test suite for the base Migration class."""

    def test_migration_initialization(self):
        """Test migration object initialization."""
        migration = TestMigration001()
        assert migration.version == "001"
        assert migration.description == "Test migration for unit tests"

    def test_migration_string_representation(self):
        """Test string representation of migration."""
        migration = TestMigration001()
        assert str(migration) == "Migration 001: Test migration for unit tests"
        assert repr(migration) == "Migration(version='001', description='Test migration for unit tests')"

    async def test_migration_up_down_methods_exist(self):
        """Test that up and down methods are properly implemented."""
        migration = TestMigration001()
        assert hasattr(migration, 'up')
        assert hasattr(migration, 'down')
        assert callable(migration.up)
        assert callable(migration.down)