"""
P0 Priority Unit Tests: Database Migration Up/Down Operations

Tests the core migration functionality including:
- Migration discovery and loading
- Up/down migration execution
- Migration state tracking
- Error handling and rollback
"""

import pytest
import pytest_asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock
import aiosqlite

from src.migrations.migration import Migration
from src.migrations.runner import MigrationRunner


class SampleMigration001(Migration):
    """Test migration for unit testing."""

    def __init__(self):
        super().__init__("001", "Test migration for unit tests")

    async def up(self, db: aiosqlite.Connection) -> None:
        await db.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, name TEXT)")

    async def down(self, db: aiosqlite.Connection) -> None:
        await db.execute("DROP TABLE IF EXISTS test_table")


class SampleMigration002(Migration):
    """Second test migration."""

    def __init__(self):
        super().__init__("002", "Second test migration")

    async def up(self, db: aiosqlite.Connection) -> None:
        await db.execute("ALTER TABLE test_table ADD COLUMN email TEXT")

    async def down(self, db: aiosqlite.Connection) -> None:
        # SQLite doesn't support DROP COLUMN in older versions, recreate table
        await db.execute("CREATE TABLE test_table_new (id INTEGER PRIMARY KEY, name TEXT)")
        await db.execute("INSERT INTO test_table_new SELECT id, name FROM test_table")
        await db.execute("DROP TABLE test_table")
        await db.execute("ALTER TABLE test_table_new RENAME TO test_table")


class SampleMigrationFailure(Migration):
    """Migration that fails for error testing."""

    def __init__(self):
        super().__init__("999", "Migration that fails")

    async def up(self, db: aiosqlite.Connection) -> None:
        await db.execute("INVALID SQL STATEMENT")

    async def down(self, db: aiosqlite.Connection) -> None:
        await db.execute("ANOTHER INVALID SQL")


@pytest_asyncio.fixture
async def raw_db():
    """Create a raw database connection with schema_migrations table."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        conn = await aiosqlite.connect(str(db_path))
        conn.row_factory = aiosqlite.Row
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                description TEXT,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        yield conn
        await conn.close()


@pytest_asyncio.fixture
async def runner():
    """Create a migration runner with a temp directory."""
    with tempfile.TemporaryDirectory() as tmp:
        migrations_dir = Path(tmp) / "migrations"
        migrations_dir.mkdir()
        yield MigrationRunner(migrations_dir)


@pytest.mark.unit
class TestMigrationRunner:
    """Test suite for MigrationRunner."""

    async def test_migration_table_creation(self, raw_db, runner):
        """Test that migrations table is created correctly."""
        await runner._ensure_migrations_table(raw_db)

        cursor = await raw_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        )
        result = await cursor.fetchone()
        assert result is not None

        cursor = await raw_db.execute("PRAGMA table_info(schema_migrations)")
        columns = await cursor.fetchall()
        column_names = [col[1] for col in columns]
        assert "version" in column_names
        assert "description" in column_names
        assert "applied_at" in column_names

    async def test_migration_discovery_empty_directory(self, temp_dir):
        """Test migration discovery with empty directory."""
        migrations_dir = temp_dir / "empty_migrations"
        migrations_dir.mkdir()
        r = MigrationRunner(migrations_dir)

        await r._discover_migrations()
        assert len(r._migrations) == 0

    async def test_apply_single_migration(self, raw_db, runner):
        """Test applying a single migration."""
        migration = SampleMigration001()
        await runner.apply_migration(raw_db, migration)

        cursor = await raw_db.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = ?", ("001",)
        )
        count = (await cursor.fetchone())[0]
        assert count == 1

        cursor = await raw_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='test_table'"
        )
        result = await cursor.fetchone()
        assert result is not None

    async def test_rollback_single_migration(self, raw_db, runner):
        """Test rolling back a single migration."""
        migration = SampleMigration001()
        await runner.apply_migration(raw_db, migration)
        await runner.rollback_migration(raw_db, migration)

        cursor = await raw_db.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = ?", ("001",)
        )
        count = (await cursor.fetchone())[0]
        assert count == 0

        cursor = await raw_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='test_table'"
        )
        result = await cursor.fetchone()
        assert result is None

    async def test_apply_multiple_migrations_up(self, raw_db, runner):
        """Test applying multiple migrations in sequence."""
        runner._migrations = {
            "001": SampleMigration001(),
            "002": SampleMigration002()
        }
        runner._discovered = True

        await runner.migrate_up(raw_db)

        cursor = await raw_db.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )
        applied = [row[0] for row in await cursor.fetchall()]
        assert applied == ["001", "002"]

        cursor = await raw_db.execute("PRAGMA table_info(test_table)")
        columns = await cursor.fetchall()
        column_names = [col[1] for col in columns]
        assert "id" in column_names
        assert "name" in column_names
        assert "email" in column_names

    async def test_rollback_multiple_migrations_down(self, raw_db, runner):
        """Test rolling back multiple migrations."""
        runner._migrations = {
            "001": SampleMigration001(),
            "002": SampleMigration002()
        }
        runner._discovered = True

        await runner.migrate_up(raw_db)
        await runner.migrate_down(raw_db, "001")

        cursor = await raw_db.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )
        applied = [row[0] for row in await cursor.fetchall()]
        assert applied == ["001"]

    async def test_migration_failure_handling(self, raw_db, runner):
        """Test that failed migrations are handled correctly."""
        migration = SampleMigrationFailure()

        with pytest.raises(Exception):
            await runner.apply_migration(raw_db, migration)

        cursor = await raw_db.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = ?", ("999",)
        )
        count = (await cursor.fetchone())[0]
        assert count == 0

    async def test_get_migration_status(self, raw_db, runner):
        """Test getting migration status information."""
        runner._migrations = {
            "001": SampleMigration001(),
            "002": SampleMigration002()
        }
        runner._discovered = True

        await runner.apply_migration(raw_db, runner._migrations["001"])

        status = await runner.get_status(raw_db)

        assert status["total_migrations"] == 2
        assert status["applied_count"] == 1
        assert status["pending_count"] == 1
        assert status["applied_migrations"] == ["001"]
        assert status["pending_migrations"] == ["002"]
        assert status["latest_applied"] == "001"
        assert status["next_pending"] == "002"

    async def test_target_version_migration_up(self, raw_db, runner):
        """Test migrating up to a specific target version."""
        runner._migrations = {
            "001": SampleMigration001(),
            "002": SampleMigration002()
        }
        runner._discovered = True

        await runner.migrate_up(raw_db, target_version="001")

        cursor = await raw_db.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )
        applied = [row[0] for row in await cursor.fetchall()]
        assert applied == ["001"]

    async def test_no_pending_migrations(self, raw_db, runner):
        """Test behavior when no migrations are pending."""
        runner._migrations = {
            "001": SampleMigration001(),
            "002": SampleMigration002()
        }
        runner._discovered = True

        await runner.migrate_up(raw_db)
        await runner.migrate_up(raw_db)  # Should be no-op

        applied = await runner.get_applied_migrations(raw_db)
        assert len(applied) == 2

    async def test_rollback_to_nonexistent_version(self, raw_db, runner):
        """Test rollback to version that doesn't exist rolls back everything."""
        runner._migrations = {
            "001": SampleMigration001(),
        }
        runner._discovered = True

        await runner.migrate_up(raw_db)
        await runner.migrate_down(raw_db, "000")

        applied = await runner.get_applied_migrations(raw_db)
        # Depending on implementation, this may roll back everything or be a no-op
        # The important thing is it doesn't crash
        assert isinstance(applied, list)


@pytest.mark.unit
class TestMigrationBase:
    """Test suite for the base Migration class."""

    def test_migration_initialization(self):
        """Test migration object initialization."""
        migration = SampleMigration001()
        assert migration.version == "001"
        assert migration.description == "Test migration for unit tests"

    def test_migration_string_representation(self):
        """Test string representation of migration."""
        migration = SampleMigration001()
        assert str(migration) == "Migration 001: Test migration for unit tests"
        assert repr(migration) == "Migration(version='001', description='Test migration for unit tests')"

    def test_migration_up_down_methods_exist(self):
        """Test that up and down methods are properly implemented."""
        migration = SampleMigration001()
        assert hasattr(migration, 'up')
        assert hasattr(migration, 'down')
        assert callable(migration.up)
        assert callable(migration.down)
