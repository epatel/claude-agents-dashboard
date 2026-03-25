"""
Smoke Tests: Basic Functionality Verification

Quick tests to verify that core components are working correctly.
These tests should run fast and catch major regressions.
"""

import pytest
from pathlib import Path

from src.database import Database
from src.migrations.runner import MigrationRunner
from src.agent.orchestrator import AgentOrchestrator


@pytest.mark.smoke
class TestBasicFunctionality:
    """Basic smoke tests for core components."""

    async def test_database_connection(self, test_db):
        """Test basic database connection and operations."""
        async with test_db.connect() as conn:
            # Simple query to verify connection works
            cursor = await conn.execute("SELECT 1 as test")
            result = await cursor.fetchone()
            assert result[0] == 1

    async def test_migration_runner_initialization(self, temp_dir):
        """Test that migration runner can be initialized."""
        migrations_dir = temp_dir / "migrations"
        migrations_dir.mkdir()

        runner = MigrationRunner(migrations_dir)
        assert runner.migrations_dir == migrations_dir
        assert runner._discovered is False

    async def test_orchestrator_initialization(
        self, temp_dir, test_db, mock_websocket_manager
    ):
        """Test that orchestrator can be initialized."""
        target_project = temp_dir / "project"
        target_project.mkdir()
        data_dir = temp_dir / "data"
        data_dir.mkdir()

        orchestrator = AgentOrchestrator(
            target_project=target_project,
            data_dir=data_dir,
            db=test_db,
            ws_manager=mock_websocket_manager
        )

        assert orchestrator.target_project == target_project
        assert orchestrator.data_dir == data_dir
        assert orchestrator.worktree_dir == data_dir / "worktrees"
        assert orchestrator.worktree_dir.exists()

    async def test_basic_item_operations(self, test_db, test_item_data):
        """Test basic database item operations."""
        async with test_db.connect() as conn:
            # Insert test item
            await conn.execute(
                """INSERT INTO items (id, title, description, column_name, position)
                   VALUES (?, ?, ?, ?, ?)""",
                (test_item_data["id"], test_item_data["title"],
                 test_item_data["description"], test_item_data["column_name"],
                 test_item_data["position"])
            )
            await conn.commit()

            # Retrieve and verify
            cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (test_item_data["id"],))
            item = dict(await cursor.fetchone())

            assert item["id"] == test_item_data["id"]
            assert item["title"] == test_item_data["title"]
            assert item["column_name"] == test_item_data["column_name"]

    async def test_migration_table_creation(self, test_db_connection):
        """Test that migration infrastructure can create its table."""
        runner = MigrationRunner(Path("/tmp"))  # Directory doesn't matter for this test
        await runner._ensure_migrations_table(test_db_connection)

        # Verify table was created
        cursor = await test_db_connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        )
        result = await cursor.fetchone()
        assert result is not None

    async def test_work_log_operations(self, test_db, test_item_data):
        """Test basic work log functionality."""
        # First create an item
        async with test_db.connect() as conn:
            await conn.execute(
                """INSERT INTO items (id, title, description, column_name, position)
                   VALUES (?, ?, ?, ?, ?)""",
                (test_item_data["id"], test_item_data["title"],
                 test_item_data["description"], test_item_data["column_name"],
                 test_item_data["position"])
            )

            # Add work log entry
            await conn.execute(
                "INSERT INTO work_log (item_id, entry_type, content) VALUES (?, ?, ?)",
                (test_item_data["id"], "system", "Test log entry")
            )
            await conn.commit()

            # Verify log entry
            cursor = await conn.execute(
                "SELECT * FROM work_log WHERE item_id = ?", (test_item_data["id"],)
            )
            log_entry = dict(await cursor.fetchone())

            assert log_entry["item_id"] == test_item_data["id"]
            assert log_entry["entry_type"] == "system"
            assert log_entry["content"] == "Test log entry"


@pytest.mark.smoke
class TestImportStructure:
    """Test that all modules can be imported correctly."""

    def test_core_imports(self):
        """Test importing core modules."""
        from src.database import Database
        from src.migrations.runner import MigrationRunner
        from src.migrations.migration import Migration
        from src.agent.orchestrator import AgentOrchestrator

        assert callable(Database)
        assert callable(MigrationRunner)
        assert callable(Migration)
        assert callable(AgentOrchestrator)

    def test_web_imports(self):
        """Test importing web-related modules."""
        from src.web.app import create_app
        from src.web.routes import router
        from src.web.websocket import ConnectionManager

        assert callable(create_app)
        assert router is not None
        assert callable(ConnectionManager)

    def test_git_imports(self):
        """Test importing git operation modules."""
        from src.git.operations import get_main_branch, merge_branch
        from src.git.worktree import create_worktree, cleanup_worktree

        assert callable(get_main_branch)
        assert callable(merge_branch)
        assert callable(create_worktree)
        assert callable(cleanup_worktree)


@pytest.mark.smoke
class TestConfigurationAndEnvironment:
    """Test basic configuration and environment setup."""

    def test_requirements_consistency(self):
        """Test that requirements.txt exists and contains expected packages."""
        requirements_file = Path("requirements.txt")
        assert requirements_file.exists()

        content = requirements_file.read_text()
        required_packages = [
            "fastapi", "uvicorn", "aiosqlite", "claude-agent-sdk",
            "pytest", "pytest-asyncio"
        ]

        for package in required_packages:
            assert package in content, f"Required package {package} not found in requirements.txt"

    def test_test_directory_structure(self):
        """Test that test directories are properly structured."""
        tests_dir = Path("tests")
        assert tests_dir.exists()
        assert tests_dir.is_dir()

        assert (tests_dir / "unit").exists()
        assert (tests_dir / "integration").exists()
        assert (tests_dir / "smoke").exists()
        assert (tests_dir / "conftest.py").exists()

    def test_pytest_configuration(self):
        """Test that pytest configuration exists and is valid."""
        pytest_ini = Path("pytest.ini")
        assert pytest_ini.exists()

        content = pytest_ini.read_text()
        assert "asyncio_mode" in content
        assert "testpaths" in content
        assert "markers" in content
