"""Shared pytest fixtures and configuration for all tests."""

import asyncio
import tempfile
import shutil
from pathlib import Path
from typing import AsyncGenerator, Generator
import pytest
import pytest_asyncio
import aiosqlite
from unittest.mock import AsyncMock, MagicMock

from src.database import Database
from src.migrations.runner import MigrationRunner
from src.agent.orchestrator import AgentOrchestrator
from src.web.websocket import ConnectionManager


@pytest_asyncio.fixture
async def temp_dir() -> AsyncGenerator[Path, None]:
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as temp_path:
        yield Path(temp_path)


@pytest_asyncio.fixture
async def test_db(temp_dir: Path) -> AsyncGenerator[Database, None]:
    """Create a test database instance."""
    db_path = temp_dir / "test.db"
    db = Database(db_path)

    # Initialize database
    await db.initialize()

    yield db


@pytest_asyncio.fixture
async def test_db_connection(test_db: Database) -> AsyncGenerator[aiosqlite.Connection, None]:
    """Get a connection to the test database."""
    async with test_db.connect() as conn:
        yield conn


@pytest_asyncio.fixture
async def migration_runner(temp_dir: Path) -> MigrationRunner:
    """Create a migration runner with test migrations directory."""
    migrations_dir = temp_dir / "migrations"
    migrations_dir.mkdir(exist_ok=True)
    return MigrationRunner(migrations_dir)


@pytest.fixture
def mock_websocket_manager() -> ConnectionManager:
    """Create a mock websocket connection manager."""
    manager = MagicMock(spec=ConnectionManager)
    manager.broadcast = AsyncMock()
    return manager


@pytest_asyncio.fixture
async def test_orchestrator(
    temp_dir: Path,
    test_db: Database,
    mock_websocket_manager: ConnectionManager
) -> AsyncGenerator[AgentOrchestrator, None]:
    """Create a test orchestrator instance."""
    import subprocess
    target_project = temp_dir / "project"
    target_project.mkdir()
    # Initialize as git repo so git operations don't fail
    subprocess.run(["git", "init", str(target_project)], capture_output=True)
    subprocess.run(["git", "-C", str(target_project), "commit", "--allow-empty", "-m", "init"], capture_output=True)

    data_dir = temp_dir / "data"
    data_dir.mkdir()

    orchestrator = AgentOrchestrator(
        target_project=target_project,
        data_dir=data_dir,
        db=test_db,
        ws_manager=mock_websocket_manager
    )

    yield orchestrator

    # Cleanup
    await orchestrator.shutdown()


@pytest.fixture
def test_item_data() -> dict:
    """Sample test item data."""
    return {
        "id": "test-item-123",
        "title": "Test Task",
        "description": "A test task for automated testing",
        "column_name": "todo",
        "position": 0,
        "status": None,
        "branch_name": None,
        "worktree_path": None,
        "commit_message": None,
        "model": None,
        "session_id": None
    }


@pytest_asyncio.fixture
async def test_item(test_db: Database, test_item_data: dict) -> dict:
    """Create a test item in the database."""
    async with test_db.connect() as conn:
        # Create the item
        await conn.execute(
            """INSERT INTO items
               (id, title, description, column_name, position, status,
                branch_name, worktree_path, commit_message, model, session_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                test_item_data["id"],
                test_item_data["title"],
                test_item_data["description"],
                test_item_data["column_name"],
                test_item_data["position"],
                test_item_data["status"],
                test_item_data["branch_name"],
                test_item_data["worktree_path"],
                test_item_data["commit_message"],
                test_item_data["model"],
                test_item_data["session_id"]
            )
        )
        await conn.commit()

        # Retrieve the created item with timestamps
        cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (test_item_data["id"],))
        row = await cursor.fetchone()
        return dict(row)


@pytest.fixture
def mock_git_operations():
    """Mock git operations to avoid actual git calls in tests."""
    import src.git.worktree as worktree_module
    import src.git.operations as operations_module

    # Mock worktree operations
    create_worktree_mock = AsyncMock(return_value=(Path("/mock/worktree"), "main", "abc123def456"))
    remove_worktree_mock = AsyncMock()
    cleanup_worktree_mock = AsyncMock()

    # Mock git operations
    get_main_branch_mock = AsyncMock(return_value="main")
    merge_branch_mock = AsyncMock(return_value=(True, "Merge successful"))

    original_functions = {
        'create_worktree': getattr(worktree_module, 'create_worktree', None),
        'remove_worktree': getattr(worktree_module, 'remove_worktree', None),
        'cleanup_worktree': getattr(worktree_module, 'cleanup_worktree', None),
        'get_main_branch': getattr(operations_module, 'get_main_branch', None),
        'merge_branch': getattr(operations_module, 'merge_branch', None)
    }

    # Apply mocks
    worktree_module.create_worktree = create_worktree_mock
    worktree_module.remove_worktree = remove_worktree_mock
    worktree_module.cleanup_worktree = cleanup_worktree_mock
    operations_module.get_main_branch = get_main_branch_mock
    operations_module.merge_branch = merge_branch_mock

    mocks = {
        'create_worktree': create_worktree_mock,
        'remove_worktree': remove_worktree_mock,
        'cleanup_worktree': cleanup_worktree_mock,
        'get_main_branch': get_main_branch_mock,
        'merge_branch': merge_branch_mock
    }

    yield mocks

    # Restore original functions
    for func_name, original_func in original_functions.items():
        if original_func is not None:
            if func_name in ['create_worktree', 'remove_worktree', 'cleanup_worktree']:
                setattr(worktree_module, func_name, original_func)
            else:
                setattr(operations_module, func_name, original_func)
