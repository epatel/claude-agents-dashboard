"""
Additional Unit Tests: Migration Edge Cases and Error Scenarios

Tests edge cases and error conditions for database migrations including:
- Malformed migration files
- Missing migration dependencies
- Concurrent migration scenarios
- Migration file discovery issues
- Database connection failures
"""

import pytest
import pytest_asyncio
import tempfile
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
import aiosqlite

from src.migrations.migration import Migration
from src.migrations.runner import MigrationRunner


class ConcurrentSafeMigration(Migration):
    """Migration designed to test concurrent access."""
    def __init__(self):
        super().__init__("concurrent", "Test concurrent access")
        self.up_call_count = 0

    async def up(self, db: aiosqlite.Connection) -> None:
        self.up_call_count += 1
        await asyncio.sleep(0.01)
        await db.execute("CREATE TABLE IF NOT EXISTS concurrent_test (id INTEGER PRIMARY KEY)")

    async def down(self, db: aiosqlite.Connection) -> None:
        await db.execute("DROP TABLE IF EXISTS concurrent_test")


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
class TestMigrationEdgeCases:
    """Test edge cases and error scenarios for migrations."""

    async def test_malformed_migration_file_handling(self, temp_dir):
        """Test that malformed migration files are handled gracefully."""
        migrations_dir = temp_dir / "migrations"
        migrations_dir.mkdir()

        bad_file = migrations_dir / "001_bad_migration.py"
        bad_file.write_text("""
# This file has syntax errors
def invalid_syntax(
    # Missing closing parenthesis

class NotAMigration:
    pass
""")

        r = MigrationRunner(migrations_dir)
        await r._discover_migrations()
        assert len(r._migrations) == 0

    async def test_migration_file_without_migration_class(self, temp_dir):
        """Test handling of Python files without Migration classes."""
        migrations_dir = temp_dir / "migrations"
        migrations_dir.mkdir()

        util_file = migrations_dir / "002_utils.py"
        util_file.write_text("""
def some_utility_function():
    return "helper"

class RegularClass:
    pass
""")

        r = MigrationRunner(migrations_dir)
        await r._discover_migrations()
        assert len(r._migrations) == 0

    async def test_migration_file_with_multiple_migration_classes(self, temp_dir):
        """Test handling files with multiple Migration classes."""
        migrations_dir = temp_dir / "migrations"
        migrations_dir.mkdir()

        multi_file = migrations_dir / "003_multiple.py"
        multi_file.write_text("""
from src.migrations.migration import Migration
import aiosqlite

class FirstMigration(Migration):
    def __init__(self):
        super().__init__("003a", "First migration")

    async def up(self, db):
        await db.execute("CREATE TABLE first (id INTEGER)")

    async def down(self, db):
        await db.execute("DROP TABLE first")

class SecondMigration(Migration):
    def __init__(self):
        super().__init__("003b", "Second migration")

    async def up(self, db):
        await db.execute("CREATE TABLE second (id INTEGER)")

    async def down(self, db):
        await db.execute("DROP TABLE second")
""")

        r = MigrationRunner(migrations_dir)
        await r._discover_migrations()

        # Should pick up the first Migration class it finds
        assert len(r._migrations) == 1
        assert "003" in r._migrations

    async def test_migration_with_database_error_during_discovery(self, temp_dir):
        """Test migration discovery when database operations fail."""
        migrations_dir = temp_dir / "migrations"
        migrations_dir.mkdir()

        good_file = migrations_dir / "004_good.py"
        good_file.write_text("""
from src.migrations.migration import Migration
import aiosqlite

class GoodMigration(Migration):
    def __init__(self):
        super().__init__("004", "Good migration")

    async def up(self, db):
        await db.execute("CREATE TABLE good (id INTEGER)")

    async def down(self, db):
        await db.execute("DROP TABLE good")
""")

        r = MigrationRunner(migrations_dir)
        await r._discover_migrations()
        assert len(r._migrations) == 1

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=Exception("Database connection lost"))

        with pytest.raises(Exception, match="Database connection lost"):
            await r.apply_migration(mock_db, r._migrations["004"])

    async def test_concurrent_migration_applications(self, raw_db):
        """Test applying the same migration concurrently."""
        with tempfile.TemporaryDirectory() as tmp:
            r = MigrationRunner(Path(tmp) / "migrations")
            migration = ConcurrentSafeMigration()
            r._migrations = {"concurrent": migration}
            r._discovered = True

            # One should succeed, one might fail due to constraint violation
            results = await asyncio.gather(
                r.apply_migration(raw_db, migration),
                r.apply_migration(raw_db, migration),
                return_exceptions=True
            )

            success_count = sum(1 for res in results if not isinstance(res, Exception))
            assert success_count >= 1

    async def test_rollback_of_non_applied_migration(self, raw_db, runner):
        """Test rolling back a migration that was never applied."""
        class SimpleMigration(Migration):
            def __init__(self):
                super().__init__("never_applied", "Never applied")
            async def up(self, db): pass
            async def down(self, db): pass

        migration = SimpleMigration()
        await runner.rollback_migration(raw_db, migration)

        cursor = await raw_db.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = ?", ("never_applied",)
        )
        count = (await cursor.fetchone())[0]
        assert count == 0

    async def test_migration_runner_with_nonexistent_directory(self):
        """Test migration runner with directory that doesn't exist."""
        nonexistent_dir = Path("/nonexistent/migrations")
        r = MigrationRunner(nonexistent_dir)

        await r._discover_migrations()
        assert len(r._migrations) == 0

    async def test_get_status_with_orphaned_migration_records(self, raw_db):
        """Test status when database has records for missing migration files."""
        with tempfile.TemporaryDirectory() as tmp:
            r = MigrationRunner(Path(tmp) / "migrations")

            await r._ensure_migrations_table(raw_db)
            await raw_db.execute(
                "INSERT INTO schema_migrations (version, description) VALUES (?, ?)",
                ("orphaned", "Missing migration file")
            )

            status = await r.get_status(raw_db)

            assert status["total_migrations"] == 0
            assert status["applied_count"] == 1
            assert "orphaned" in status["applied_migrations"]

    async def test_migration_with_very_long_version_string(self, raw_db, runner):
        """Test migration with unusually long version string."""
        class LongVersionMigration(Migration):
            def __init__(self):
                super().__init__(
                    "very_long_version_string_that_might_cause_issues",
                    "Migration with long version"
                )
            async def up(self, db):
                await db.execute("CREATE TABLE long_version_test (id INTEGER)")
            async def down(self, db):
                await db.execute("DROP TABLE long_version_test")

        migration = LongVersionMigration()
        await runner.apply_migration(raw_db, migration)

        cursor = await raw_db.execute(
            "SELECT version FROM schema_migrations WHERE version LIKE '%very_long%'"
        )
        result = await cursor.fetchone()
        assert result is not None

    async def test_migration_down_with_missing_table(self, raw_db, runner):
        """Test migration rollback when target table doesn't exist."""
        class TableMissingMigration(Migration):
            def __init__(self):
                super().__init__("missing_table", "Test missing table scenario")
            async def up(self, db):
                await db.execute("CREATE TABLE will_be_missing (id INTEGER)")
            async def down(self, db):
                await db.execute("DROP TABLE will_be_missing")

        migration = TableMissingMigration()
        await runner.apply_migration(raw_db, migration)

        # Manually drop the table to simulate missing table scenario
        await raw_db.execute("DROP TABLE will_be_missing")

        with pytest.raises(Exception):
            await runner.rollback_migration(raw_db, migration)

    async def test_empty_migration_methods(self, raw_db, runner):
        """Test migration with empty up/down methods."""
        class EmptyMigration(Migration):
            def __init__(self):
                super().__init__("empty", "Empty migration")
            async def up(self, db): pass
            async def down(self, db): pass

        migration = EmptyMigration()
        await runner.apply_migration(raw_db, migration)

        cursor = await raw_db.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = ?", ("empty",)
        )
        assert (await cursor.fetchone())[0] == 1

        await runner.rollback_migration(raw_db, migration)

        cursor = await raw_db.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = ?", ("empty",)
        )
        assert (await cursor.fetchone())[0] == 0

    async def test_migration_version_ordering_edge_cases(self, raw_db):
        """Test migration ordering with edge case version numbers."""
        with tempfile.TemporaryDirectory() as tmp:
            r = MigrationRunner(Path(tmp) / "migrations")

            versions = ["001", "002", "010", "100"]
            migrations = {}

            for ver in versions:
                class VersionedMigration(Migration):
                    def __init__(self, v=ver):
                        super().__init__(v, f"Test migration {v}")
                        self._ver = v
                    async def up(self, db):
                        await db.execute(f"CREATE TABLE test_{self._ver} (id INTEGER)")
                    async def down(self, db):
                        await db.execute(f"DROP TABLE test_{self._ver}")

                migrations[ver] = VersionedMigration(ver)

            r._migrations = migrations
            r._discovered = True

            await r.migrate_up(raw_db)

            cursor = await raw_db.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
            applied_versions = [row[0] for row in await cursor.fetchall()]
            assert applied_versions == sorted(versions)


@pytest.mark.unit
class TestMigrationDiscoveryPerformance:
    """Test performance aspects of migration discovery."""

    async def test_large_number_of_migration_files(self, temp_dir):
        """Test discovery performance with many migration files."""
        migrations_dir = temp_dir / "migrations"
        migrations_dir.mkdir()

        for i in range(100):
            migration_file = migrations_dir / f"{i:03d}_migration_{i}.py"
            migration_file.write_text(f"""
from src.migrations.migration import Migration

class Migration{i:03d}(Migration):
    def __init__(self):
        super().__init__("{i:03d}", "Migration {i}")

    async def up(self, db): pass
    async def down(self, db): pass
""")

        r = MigrationRunner(migrations_dir)

        import time
        start = time.time()
        await r._discover_migrations()
        end = time.time()

        assert len(r._migrations) == 100
        assert (end - start) < 1.0

    async def test_repeated_discovery_caching(self, temp_dir):
        """Test that repeated discovery uses caching."""
        migrations_dir = temp_dir / "migrations"
        migrations_dir.mkdir()

        migration_file = migrations_dir / "001_test.py"
        migration_file.write_text("""
from src.migrations.migration import Migration

class TestMigration(Migration):
    def __init__(self):
        super().__init__("001", "Test")

    async def up(self, db): pass
    async def down(self, db): pass
""")

        r = MigrationRunner(migrations_dir)

        await r._discover_migrations()
        first_count = len(r._migrations)

        await r._discover_migrations()
        second_count = len(r._migrations)

        assert first_count == second_count == 1
        assert r._discovered is True
