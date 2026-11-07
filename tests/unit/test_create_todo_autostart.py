"""Tests that would have caught bugs fixed in recent commits.

Each test is annotated with the commit that fixed the bug it covers.
These serve as regression tests to prevent re-introduction.
"""

import asyncio
import pytest
import pytest_asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import tempfile

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


@pytest.fixture
def ws(db_service):
    """A bare WorkflowService wired to the test DB with mocked notifications.

    ``ws.notifications.ws_manager.broadcast`` and ``ws.start_agent`` are
    AsyncMocks the tests assert against.
    """
    from src.services.workflow_service import WorkflowService

    mock_notifications = MagicMock()
    mock_notifications.broadcast_item_created = AsyncMock()
    mock_notifications.ws_manager = MagicMock()
    mock_notifications.ws_manager.broadcast = AsyncMock()

    with patch.object(WorkflowService, '__init__', lambda self, **kw: None):
        service = WorkflowService.__new__(WorkflowService)
        service.db = db_service
        service.notifications = mock_notifications
        service._log_and_notify = AsyncMock()
        service.start_agent = AsyncMock()
        yield service


def _broadcast_event_types(ws):
    """Event types passed to ws_manager.broadcast, in call order."""
    call_args = ws.notifications.ws_manager.broadcast.call_args_list
    return [c[0][0] for c in call_args]


async def _create_from_creator_in(ws, column):
    """Have a creator card sitting in ``column`` create an autostart todo.

    Returns (creator, result) where result is the callback's created item.
    """
    creator = await ws.db.create_todo_item("Creator", f"card in {column}")
    await ws.db.update_item(creator["id"], column_name=column)
    callback = ws._create_on_create_todo_callback(creator["id"])
    result = await callback("Autostart task", "desc", None, None, True)
    return creator, result


async def _drain_event_loop(ticks=5):
    """Let fire-and-forget autostart tasks run to completion."""
    for _ in range(ticks):
        await asyncio.sleep(0)


# ── Bug: create_todo autostart flag not saved (d274291) ───────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs, expected, why",
    [
        pytest.param(
            {"auto_start": True}, 1, "auto_start should be persisted as 1 (truthy)",
            id="true",
        ),
        pytest.param(
            {"auto_start": False}, 0, "auto_start should be persisted as 0",
            id="false",
        ),
        pytest.param({}, 0, "auto_start should default to 0", id="default"),
    ],
)
async def test_create_todo_item_auto_start(db_service, kwargs, expected, why):
    """create_todo_item must persist auto_start (True→1, False→0, omitted→0).

    Regression for d274291: auto_start parameter was accepted but never
    included in the INSERT statement, so it was silently dropped.
    """
    item = await db_service.create_todo_item("Task", "auto start check", **kwargs)
    assert item["auto_start"] == expected, why


@pytest.mark.asyncio
async def test_on_create_todo_callback_forwards_autostart(ws):
    """The on_create_todo callback must forward autostart to create_todo_item.

    Regression for d274291: the callback accepted autostart but never
    passed it through to db.create_todo_item().
    """
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
async def test_create_todo_callback_receives_requires_and_autostart(ws):
    """The on_create_todo callback must receive requires and autostart params.

    Tests that the callback signature and forwarding work correctly.
    """
    dep1 = await ws.db.create_todo_item("Dep 1", "First dep")
    dep2 = await ws.db.create_todo_item("Dep 2", "Second dep")

    callback = ws._create_on_create_todo_callback("parent-123")
    result = await callback("New Task", "desc", None, [dep1["id"], dep2["id"]], True)

    # Verify the item was created with autostart flag
    assert result["auto_start"] == 1
    # Verify dependencies were recorded
    async with ws.db.db.connect() as conn:
        cursor = await conn.execute(
            "SELECT requires_item_id FROM item_dependencies WHERE item_id = ?",
            (result["id"],),
        )
        dep_ids = [row[0] for row in await cursor.fetchall()]
    assert dep1["id"] in dep_ids
    assert dep2["id"] in dep_ids


@pytest.mark.asyncio
async def test_create_todo_callback_sets_dependencies_in_db(ws):
    """Dependencies passed via requires must be stored in item_dependencies table."""
    dep = await ws.db.create_todo_item("Prerequisite", "Must do first")
    callback = ws._create_on_create_todo_callback("parent-123")
    await callback("Dependent Task", "needs prereq", None, [dep["id"]], False)

    # Verify blocked_status_changed was broadcast
    ws.notifications.ws_manager.broadcast.assert_called()
    assert "blocked_status_changed" in _broadcast_event_types(ws), \
        "Should broadcast blocked_status_changed when dependencies are set"


@pytest.mark.asyncio
async def test_create_todo_callback_no_requires_no_blocked_broadcast(ws):
    """When no requires, blocked_status_changed should NOT be broadcast."""
    callback = ws._create_on_create_todo_callback("parent-123")
    await callback("Simple Task", "no deps", None, None, False)

    # blocked_status_changed should NOT have been broadcast
    if ws.notifications.ws_manager.broadcast.called:
        assert "blocked_status_changed" not in _broadcast_event_types(ws)


# ── Bug: autostart with dependencies should not start immediately ────


@pytest.mark.asyncio
async def test_callback_does_not_immediately_start_with_dependencies(ws):
    """When autostart=True but requires is set, agent should NOT start immediately.

    The agent should only auto-start once dependencies are completed.
    """
    dep_item = await ws.db.create_todo_item("Dependency", "Must finish first")

    callback = ws._create_on_create_todo_callback("parent-item-123")
    result = await callback("Blocked Task", "desc", None, [dep_item["id"]], True)

    # start_agent should NOT have been called since there are unmet dependencies
    ws.start_agent.assert_not_called()
    # But auto_start should be persisted for deferred start
    assert result["auto_start"] == 1


@pytest.mark.asyncio
async def test_autostart_empty_requires_anchors_to_creating_card(ws):
    """autostart + no requires, created by an in-flight agent, must NOT start
    immediately. Instead it auto-anchors a dependency on the creating card so it
    waits for that work to merge (avoids branching off an unmerged main)."""
    # The creating agent's card exists and is in flight (column 'doing').
    creator, result = await _create_from_creator_in(ws, "doing")

    # Must not start immediately — it now depends on the creator.
    ws.start_agent.assert_not_called()
    assert result["auto_start"] == 1
    deps = await ws.db.get_item_dependencies(result["id"])
    assert [d["id"] for d in deps] == [creator["id"]]


@pytest.mark.asyncio
async def test_autostart_empty_requires_starts_immediately_when_creator_done(ws):
    """If the creating card has already merged (done), its work is on main, so an
    autostart task with no deps can safely start immediately (no anchor added)."""
    _creator, result = await _create_from_creator_in(ws, "done")
    await _drain_event_loop()

    ws.start_agent.assert_called_once_with(result["id"])
    deps = await ws.db.get_item_dependencies(result["id"])
    assert deps == []


# ── auto_approve persistence (create_todo MCP tool can request it) ───


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs, expected",
    [
        pytest.param({"auto_approve": 1}, 1, id="review"),
        pytest.param({"auto_approve": 2}, 2, id="direct"),
        pytest.param({}, 0, id="default_is_off"),
        pytest.param({"auto_approve": 42}, 0, id="invalid_falls_back_to_off"),
    ],
)
async def test_create_todo_item_persists_auto_approve(db_service, kwargs, expected):
    """create_todo_item must persist the auto_approve mode passed in.

    1 (review) and 2 (direct) are stored as-is; omitted defaults to 0 (OFF);
    out-of-range values are coerced to 0.
    """
    item = await db_service.create_todo_item("Task", "auto approve check", **kwargs)
    assert item["auto_approve"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra_args, expected",
    [
        # autostart=False, auto_approve=2 (direct)
        pytest.param((2,), 2, id="forwards_direct"),
        # Invalid auto_approve values are coerced to OFF before hitting the db
        pytest.param((99,), 0, id="invalid_coerced_to_off"),
        # Legacy 5-positional-arg call site: auto_approve defaults to 0
        pytest.param((), 0, id="legacy_default_is_off"),
    ],
)
async def test_callback_forwards_auto_approve_to_db(ws, extra_args, expected):
    """The on_create_todo callback must forward auto_approve to create_todo_item."""
    callback = ws._create_on_create_todo_callback("parent-123")
    result = await callback("Task", "desc", None, None, False, *extra_args)

    assert result["auto_approve"] == expected


@pytest.mark.asyncio
async def test_callback_supports_autostart_and_auto_approve_together(ws):
    """Callback must accept both autostart and auto_approve in the same call."""
    callback = ws._create_on_create_todo_callback("parent-123")
    result = await callback("Both", "desc", None, None, True, 1)

    # Give the asyncio.create_task a chance to run (autostart with no deps)
    await asyncio.sleep(0.1)

    ws.start_agent.assert_called_once()
    assert result["auto_start"] == 1
    assert result["auto_approve"] == 1
    assert result.get("autostart_scheduled") is True


@pytest.mark.asyncio
async def test_callback_starts_agent_immediately_without_dependencies(ws):
    """When autostart=True and no requires, agent should start immediately.

    Here the creating id ("parent-item-123") is not a real card, so the
    in-flight auto-anchor does not apply and the immediate-start path runs.
    The anchored path (creator exists & in flight) is covered separately by
    test_autostart_empty_requires_anchors_to_creating_card.
    """
    callback = ws._create_on_create_todo_callback("parent-item-123")
    result = await callback("Immediate Task", "desc", None, None, True)

    # Give the asyncio.create_task a chance to run
    await asyncio.sleep(0.1)

    # start_agent SHOULD have been called for immediate autostart
    ws.start_agent.assert_called_once()
    assert result.get("autostart_scheduled") is True
