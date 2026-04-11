"""Tests that would have caught bugs fixed in recent commits.

Each test is annotated with the commit that fixed the bug it covers.
These serve as regression tests to prevent re-introduction.
"""

import pytest
import pytest_asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import tempfile
import asyncio

from src.database import Database
from src.services.database_service import DatabaseService
from src.agent.todo import CREATE_TODO_SCHEMA


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db():
    """Create a test database with all migrations applied."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        database = Database(db_path)
        await database.initialize()
        yield database


@pytest_asyncio.fixture
async def db_service(db):
    """Create a DatabaseService instance."""
    return DatabaseService(db)


# ── Bug: create_todo autostart flag not saved (d274291) ───────────────


@pytest.mark.asyncio
async def test_create_todo_item_with_auto_start_true(db_service):
    """create_todo_item(auto_start=True) must persist auto_start=1 in DB.

    Regression for d274291: auto_start parameter was accepted but never
    included in the INSERT statement, so it was silently dropped.
    """
    item = await db_service.create_todo_item("Auto Task", "Should auto start", auto_start=True)
    assert item["auto_start"] == 1, "auto_start should be persisted as 1 (truthy)"


@pytest.mark.asyncio
async def test_create_todo_item_with_auto_start_false(db_service):
    """create_todo_item(auto_start=False) must persist auto_start=0."""
    item = await db_service.create_todo_item("Manual Task", "No auto start", auto_start=False)
    assert item["auto_start"] == 0, "auto_start should be persisted as 0"


@pytest.mark.asyncio
async def test_create_todo_item_auto_start_default(db_service):
    """create_todo_item without auto_start defaults to False/0."""
    item = await db_service.create_todo_item("Default Task", "Default behavior")
    assert item["auto_start"] == 0, "auto_start should default to 0"


@pytest.mark.asyncio
async def test_on_create_todo_callback_forwards_autostart(db_service):
    """The on_create_todo callback must forward autostart to create_todo_item.

    Regression for d274291: the callback accepted autostart but never
    passed it through to db.create_todo_item().
    """
    mock_notifications = MagicMock()
    mock_notifications.broadcast_item_created = AsyncMock()
    mock_notifications.ws_manager = MagicMock()
    mock_notifications.ws_manager.broadcast = AsyncMock()

    from src.services.workflow_service import WorkflowService

    with patch.object(WorkflowService, '__init__', lambda self, **kw: None):
        ws = WorkflowService.__new__(WorkflowService)
        ws.db = db_service
        ws.notifications = mock_notifications
        ws._log_and_notify = AsyncMock()
        ws.start_agent = AsyncMock()

        callback = ws._create_on_create_todo_callback("parent-item-123")
        result = await callback("Autostart Todo", "desc", None, None, True)

    # The item should be saved with auto_start=1 in the database
    assert result["auto_start"] == 1, "autostart flag must be forwarded and persisted"


# ── Bug: create_todo tool schema missing requires description (dfcd269) ──


class TestCreateTodoSchema:
    """Schema validation tests for the create_todo MCP tool.

    Regression for dfcd269: tool description lacked IMPORTANT note about
    the requires parameter for enforcing dependencies.
    """

    def test_schema_has_requires_field(self):
        """The create_todo schema must include 'requires' for dependencies."""
        assert "requires" in CREATE_TODO_SCHEMA["properties"]

    def test_requires_field_is_array_of_strings(self):
        """requires must be an array of string IDs."""
        req = CREATE_TODO_SCHEMA["properties"]["requires"]
        assert req["type"] == "array"
        assert req["items"]["type"] == "string"

    def test_schema_has_autostart_field(self):
        """The create_todo schema must include 'autostart'."""
        assert "autostart" in CREATE_TODO_SCHEMA["properties"]
        assert CREATE_TODO_SCHEMA["properties"]["autostart"]["type"] == "boolean"

    def test_autostart_description_mentions_dependencies(self):
        """autostart description should explain behavior with dependencies.

        Regression for f356af7: description was misleading about dependency behavior.
        """
        desc = CREATE_TODO_SCHEMA["properties"]["autostart"]["description"]
        assert "dependencies" in desc.lower() or "depends" in desc.lower(), \
            "autostart description should mention dependency behavior"


# ── Bug: create_todo MCP tool must forward all parameters ─────────────


@pytest.mark.asyncio
async def test_create_todo_callback_receives_requires_and_autostart(db_service):
    """The on_create_todo callback must receive requires and autostart params.

    Tests that the callback signature and forwarding work correctly.
    """
    mock_notifications = MagicMock()
    mock_notifications.broadcast_item_created = AsyncMock()
    mock_notifications.ws_manager = MagicMock()
    mock_notifications.ws_manager.broadcast = AsyncMock()

    from src.services.workflow_service import WorkflowService

    with patch.object(WorkflowService, '__init__', lambda self, **kw: None):
        ws = WorkflowService.__new__(WorkflowService)
        ws.db = db_service
        ws.notifications = mock_notifications
        ws._log_and_notify = AsyncMock()
        ws.start_agent = AsyncMock()

        # Create dependency items
        dep1 = await db_service.create_todo_item("Dep 1", "First dep")
        dep2 = await db_service.create_todo_item("Dep 2", "Second dep")

        callback = ws._create_on_create_todo_callback("parent-123")
        result = await callback("New Task", "desc", None, [dep1["id"], dep2["id"]], True)

    # Verify the item was created with autostart flag
    assert result["auto_start"] == 1
    # Verify dependencies were recorded
    async with db_service.db.connect() as conn:
        cursor = await conn.execute(
            "SELECT requires_item_id FROM item_dependencies WHERE item_id = ?",
            (result["id"],),
        )
        dep_ids = [row[0] for row in await cursor.fetchall()]
    assert dep1["id"] in dep_ids
    assert dep2["id"] in dep_ids


@pytest.mark.asyncio
async def test_create_todo_callback_sets_dependencies_in_db(db_service):
    """Dependencies passed via requires must be stored in item_dependencies table."""
    mock_notifications = MagicMock()
    mock_notifications.broadcast_item_created = AsyncMock()
    mock_notifications.ws_manager = MagicMock()
    mock_notifications.ws_manager.broadcast = AsyncMock()

    from src.services.workflow_service import WorkflowService

    with patch.object(WorkflowService, '__init__', lambda self, **kw: None):
        ws = WorkflowService.__new__(WorkflowService)
        ws.db = db_service
        ws.notifications = mock_notifications
        ws._log_and_notify = AsyncMock()
        ws.start_agent = AsyncMock()

        dep = await db_service.create_todo_item("Prerequisite", "Must do first")
        callback = ws._create_on_create_todo_callback("parent-123")
        result = await callback("Dependent Task", "needs prereq", None, [dep["id"]], False)

    # Verify blocked_status_changed was broadcast
    mock_notifications.ws_manager.broadcast.assert_called()
    call_args = mock_notifications.ws_manager.broadcast.call_args_list
    event_types = [c[0][0] for c in call_args]
    assert "blocked_status_changed" in event_types, \
        "Should broadcast blocked_status_changed when dependencies are set"


@pytest.mark.asyncio
async def test_create_todo_callback_no_requires_no_blocked_broadcast(db_service):
    """When no requires, blocked_status_changed should NOT be broadcast."""
    mock_notifications = MagicMock()
    mock_notifications.broadcast_item_created = AsyncMock()
    mock_notifications.ws_manager = MagicMock()
    mock_notifications.ws_manager.broadcast = AsyncMock()

    from src.services.workflow_service import WorkflowService

    with patch.object(WorkflowService, '__init__', lambda self, **kw: None):
        ws = WorkflowService.__new__(WorkflowService)
        ws.db = db_service
        ws.notifications = mock_notifications
        ws._log_and_notify = AsyncMock()
        ws.start_agent = AsyncMock()

        callback = ws._create_on_create_todo_callback("parent-123")
        await callback("Simple Task", "no deps", None, None, False)

    # blocked_status_changed should NOT have been broadcast
    if mock_notifications.ws_manager.broadcast.called:
        call_args = mock_notifications.ws_manager.broadcast.call_args_list
        event_types = [c[0][0] for c in call_args]
        assert "blocked_status_changed" not in event_types


# ── Bug: autostart with dependencies should not start immediately ────


@pytest.mark.asyncio
async def test_callback_does_not_immediately_start_with_dependencies(db_service):
    """When autostart=True but requires is set, agent should NOT start immediately.

    The agent should only auto-start once dependencies are completed.
    """
    mock_notifications = MagicMock()
    mock_notifications.broadcast_item_created = AsyncMock()
    mock_notifications.ws_manager = MagicMock()
    mock_notifications.ws_manager.broadcast = AsyncMock()

    from src.services.workflow_service import WorkflowService

    with patch.object(WorkflowService, '__init__', lambda self, **kw: None):
        ws = WorkflowService.__new__(WorkflowService)
        ws.db = db_service
        ws.notifications = mock_notifications
        ws._log_and_notify = AsyncMock()
        ws.start_agent = AsyncMock()

        # Create a dependency item first
        dep_item = await db_service.create_todo_item("Dependency", "Must finish first")

        callback = ws._create_on_create_todo_callback("parent-item-123")
        result = await callback("Blocked Task", "desc", None, [dep_item["id"]], True)

    # start_agent should NOT have been called since there are unmet dependencies
    ws.start_agent.assert_not_called()
    # But auto_start should be persisted for deferred start
    assert result["auto_start"] == 1


@pytest.mark.asyncio
async def test_callback_starts_agent_immediately_without_dependencies(db_service):
    """When autostart=True and no requires, agent should start immediately."""
    mock_notifications = MagicMock()
    mock_notifications.broadcast_item_created = AsyncMock()
    mock_notifications.ws_manager = MagicMock()
    mock_notifications.ws_manager.broadcast = AsyncMock()

    from src.services.workflow_service import WorkflowService

    with patch.object(WorkflowService, '__init__', lambda self, **kw: None):
        ws = WorkflowService.__new__(WorkflowService)
        ws.db = db_service
        ws.notifications = mock_notifications
        ws._log_and_notify = AsyncMock()
        ws.start_agent = AsyncMock()

        callback = ws._create_on_create_todo_callback("parent-item-123")
        result = await callback("Immediate Task", "desc", None, None, True)

        # Give the asyncio.create_task a chance to run
        await asyncio.sleep(0.1)

    # start_agent SHOULD have been called for immediate autostart
    ws.start_agent.assert_called_once()
    assert result.get("autostart_scheduled") is True
