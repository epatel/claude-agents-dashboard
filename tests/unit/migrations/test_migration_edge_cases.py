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
import tempfile
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
import aiosqlite

from src.migrations.migration import Migration
from src.migrations.runner import MigrationRunner


class MalformedMigration:
    """Migration class without proper inheritance - should be ignored."""
    def __init__(self):
        self.version = "bad"
        self.description = "This is malformed"


class IncompleteMigration(Migration):
    """Migration missing required methods."""
    def __init__(self):
        super().__init__("incomplete", "Missing methods")
    # Missing up() and down() implementations


class ConcurrentSafeMigration(Migration):
    """Migration designed to test concurrent access."""
    def __init__(self):
        super().__init__("concurrent", "Test concurrent access")
        self.up_call_count = 0
        self.down_call_count = 0

    async def up(self, db: aiosqlite.Connection) -> None:
        self.up_call_count += 1
        # Simulate some work
        await asyncio.sleep(0.01)
        await db.execute("CREATE TABLE concurrent_test (id INTEGER PRIMARY KEY)")

    async def down(self, db: aiosqlite.Connection) -> None:
        self.down_call_count += 1
        await asyncio.sleep(0.01)
        await db.execute("DROP TABLE IF EXISTS concurrent_test")


@pytest.mark.unit
class TestMigrationEdgeCases:
    """Test edge cases and error scenarios for migrations."""

    async def test_malformed_migration_file_handling(self, temp_dir):
        """Test that malformed migration files are handled gracefully."""
        migrations_dir = temp_dir / "migrations"
        migrations_dir.mkdir()

        # Create a Python file with invalid migration content
        bad_file = migrations_dir / "001_bad_migration.py"
        bad_file.write_text("""
# This file has syntax errors
def invalid_syntax(
    # Missing closing parenthesis

class NotAMigration:
    pass
""")

        runner = MigrationRunner(migrations_dir)
        await runner._discover_migrations()

        # Should not crash, just skip the bad file
        assert len(runner._migrations) == 0

    async def test_migration_file_without_migration_class(self, temp_dir):
        """Test handling of Python files without Migration classes."""
        migrations_dir = temp_dir / "migrations"
        migrations_dir.mkdir()

        # Create a valid Python file but without Migration class
        util_file = migrations_dir / "002_utils.py"
        util_file.write_text("""
def some_utility_function():
    return "helper"

class RegularClass:
    pass
""")

        runner = MigrationRunner(migrations_dir)
        await runner._discover_migrations()

        # Should ignore files without Migration classes
        assert len(runner._migrations) == 0

    async def test_migration_file_with_multiple_migration_classes(self, temp_dir):
        """Test handling files with multiple Migration classes."""
        migrations_dir = temp_dir / "migrations"
        migrations_dir.mkdir()

        # Create file with multiple Migration classes
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

        runner = MigrationRunner(migrations_dir)
        await runner._discover_migrations()

        # Should pick up the first Migration class it finds
        assert len(runner._migrations) == 1
        assert "003" in runner._migrations

    async def test_migration_with_database_error_during_discovery(self, temp_dir):
        """Test migration discovery when database operations fail."""
        migrations_dir = temp_dir / "migrations"
        migrations_dir.mkdir()

        # Create a valid migration file
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

        runner = MigrationRunner(migrations_dir)
        await runner._discover_migrations()

        assert len(runner._migrations) == 1

        # Now test with database connection that fails
        mock_db = MagicMock()
        mock_db.execute.side_effect = Exception("Database connection lost")

        with pytest.raises(Exception, match="Database connection lost"):
            await runner.apply_migration(mock_db, runner._migrations["004"])

    async def test_concurrent_migration_applications(self, test_db_connection, temp_dir):
        """Test applying the same migration concurrently (should handle gracefully)."""
        runner = MigrationRunner(temp_dir / "migrations")
        migration = ConcurrentSafeMigration()
        runner._migrations = {"concurrent": migration}
        runner._discovered = True

        # Apply the same migration concurrently
        async def apply_with_delay():
            await asyncio.sleep(0.005)  # Small delay to interleave execution
            return await runner.apply_migration(test_db_connection, migration)

        # One should succeed, one might fail due to constraint violation
        results = await asyncio.gather(
            runner.apply_migration(test_db_connection, migration),
            apply_with_delay(),
            return_exceptions=True
        )

        # At least one should succeed
        success_count = sum(1 for r in results if not isinstance(r, Exception))
        assert success_count >= 1

        # Migration should only be recorded once
        cursor = await test_db_connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = ?",
            ("concurrent",)
        )
        count = (await cursor.fetchone())[0]
        assert count == 1

    async def test_rollback_of_non_applied_migration(self, test_db_connection, migration_runner):
        """Test rolling back a migration that was never applied."""
        from tests.unit.migrations.test_migration_runner import TestMigration001

        migration = TestMigration001()

        # Try to rollback without applying first - should handle gracefully
        await migration_runner.rollback_migration(test_db_connection, migration)

        # Should not crash, migration record should not exist
        cursor = await test_db_connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = ?", ("001",)
        )
        count = (await cursor.fetchone())[0]
        assert count == 0

    async def test_migration_runner_with_nonexistent_directory(self):
        """Test migration runner with directory that doesn't exist."""
        nonexistent_dir = Path("/nonexistent/migrations")
        runner = MigrationRunner(nonexistent_dir)

        # Should handle gracefully
        await runner._discover_migrations()
        assert len(runner._migrations) == 0

    async def test_get_status_with_orphaned_migration_records(self, test_db_connection, temp_dir):
        """Test status when database has records for missing migration files."""
        runner = MigrationRunner(temp_dir / "migrations")

        # Manually insert a migration record for a non-existent migration
        await runner._ensure_migrations_table(test_db_connection)
        await test_db_connection.execute(
            "INSERT INTO schema_migrations (version, description) VALUES (?, ?)",
            ("orphaned", "Missing migration file")
        )

        status = await runner.get_status(test_db_connection)

        assert status["total_migrations"] == 0
        assert status["applied_count"] == 1
        assert status["applied_migrations"] == ["orphaned"]
        assert "orphaned" in status["applied_migrations"]

    async def test_migration_with_very_long_version_string(self, test_db_connection, migration_runner):
        """Test migration with unusually long version string."""
        class LongVersionMigration(Migration):
            def __init__(self):
                super().__init__(
                    "very_long_version_string_that_might_cause_issues_in_some_systems",
                    "Migration with long version"
                )

            async def up(self, db):
                await db.execute("CREATE TABLE long_version_test (id INTEGER)")

            async def down(self, db):
                await db.execute("DROP TABLE long_version_test")

        migration = LongVersionMigration()
        await migration_runner.apply_migration(test_db_connection, migration)

        # Check it was applied correctly
        cursor = await test_db_connection.execute(
            "SELECT version FROM schema_migrations WHERE version LIKE '%very_long%'"
        )
        result = await cursor.fetchone()
        assert result is not None
        assert "very_long_version_string" in result[0]

    async def test_migration_down_with_missing_table(self, test_db_connection, migration_runner):
        """Test migration rollback when target table doesn't exist."""
        class TableMissingMigration(Migration):
            def __init__(self):
                super().__init__("missing_table", "Test missing table scenario")

            async def up(self, db):
                await db.execute("CREATE TABLE will_be_missing (id INTEGER)")

            async def down(self, db):
                # This will fail if table doesn't exist
                await db.execute("DROP TABLE will_be_missing")

        migration = TableMissingMigration()

        # Apply migration
        await migration_runner.apply_migration(test_db_connection, migration)

        # Manually drop the table to simulate missing table scenario
        await test_db_connection.execute("DROP TABLE will_be_missing")

        # Rollback should fail
        with pytest.raises(Exception):
            await migration_runner.rollback_migration(test_db_connection, migration)

    async def test_empty_migration_methods(self, test_db_connection, migration_runner):
        """Test migration with empty up/down methods."""
        class EmptyMigration(Migration):
            def __init__(self):
                super().__init__("empty", "Empty migration")

            async def up(self, db):
                pass  # No operation

            async def down(self, db):
                pass  # No operation

        migration = EmptyMigration()

        # Should apply and rollback successfully
        await migration_runner.apply_migration(test_db_connection, migration)

        cursor = await test_db_connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = ?", ("empty",)
        )
        assert (await cursor.fetchone())[0] == 1

        await migration_runner.rollback_migration(test_db_connection, migration)

        cursor = await test_db_connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = ?", ("empty",)
        )
        assert (await cursor.fetchone())[0] == 0

    async def test_migration_version_ordering_edge_cases(self, test_db_connection, temp_dir):
        """Test migration ordering with edge case version numbers."""
        runner = MigrationRunner(temp_dir / "migrations")

        # Create migrations with different version formats
        versions = ["001", "002", "010", "100", "1000"]
        migrations = {}

        for version in versions:
            class TestMigration(Migration):
                def __init__(self, v=version):
                    super().__init__(v, f"Test migration {v}")

                async def up(self, db):
                    await db.execute(f"CREATE TABLE test_{v} (id INTEGER)")

                async def down(self, db):
                    await db.execute(f"DROP TABLE test_{v}")

            migrations[version] = TestMigration(version)

        runner._migrations = migrations
        runner._discovered = True

        # Apply all migrations
        await runner.migrate_up(test_db_connection)

        # Check they were applied in correct order
        cursor = await test_db_connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )
        applied_versions = [row[0] for row in await cursor.fetchall()]

        # Should be in lexicographic order
        assert applied_versions == sorted(versions)

@pytest.mark.unit
class TestMigrationDiscoveryPerformance:
    """Test performance aspects of migration discovery."""

    async def test_large_number_of_migration_files(self, temp_dir):
        """Test discovery performance with many migration files."""
        migrations_dir = temp_dir / "migrations"
        migrations_dir.mkdir()

        # Create many migration files
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

        runner = MigrationRunner(migrations_dir)

        # Time the discovery
        import time
        start = time.time()
        await runner._discover_migrations()
        end = time.time()

        assert len(runner._migrations) == 100
        assert (end - start) < 1.0  # Should complete within 1 second

    async def test_repeated_discovery_caching(self, temp_dir):
        """Test that repeated discovery uses caching."""
        migrations_dir = temp_dir / "migrations"
        migrations_dir.mkdir()

        # Create a migration file
        migration_file = migrations_dir / "001_test.py"
        migration_file.write_text("""
from src.migrations.migration import Migration

class TestMigration(Migration):
    def __init__(self):
        super().__init__("001", "Test")

    async def up(self, db): pass
    async def down(self, db): pass
""")

        runner = MigrationRunner(migrations_dir)

        # First discovery
        await runner._discover_migrations()
        first_count = len(runner._migrations)

        # Second discovery should use cache
        await runner._discover_migrations()
        second_count = len(runner._migrations)

        assert first_count == second_count == 1
        assert runner._discovered is True