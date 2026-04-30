"""Tests for src/repositories/item_repository.py."""

import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

from src.database import Database
from src.domain.item_state import Event, ItemState
from src.domain.item_state import InvalidTransition
from src.repositories.item_repository import ItemNotFound, ItemRepository
from src.services.database_service import DatabaseService


@pytest_asyncio.fixture
async def db():
    with tempfile.TemporaryDirectory() as d:
        database = Database(Path(d) / "test.db")
        await database.initialize()
        yield database


@pytest_asyncio.fixture
async def repo(db):
    return ItemRepository(DatabaseService(db))


@pytest_asyncio.fixture
async def db_service(db):
    return DatabaseService(db)


class TestGet:
    async def test_returns_item_when_present(self, repo, db_service):
        created = await db_service.create_todo_item("X", "")
        got = await repo.get(created["id"])
        assert got is not None
        assert got["id"] == created["id"]

    async def test_returns_none_when_missing(self, repo):
        assert await repo.get("nope") is None


class TestGetOrRaise:
    async def test_returns_item_when_present(self, repo, db_service):
        created = await db_service.create_todo_item("X", "")
        got = await repo.get_or_raise(created["id"])
        assert got["id"] == created["id"]

    async def test_raises_item_not_found(self, repo):
        with pytest.raises(ItemNotFound) as exc:
            await repo.get_or_raise("nope")
        assert exc.value.item_id == "nope"


class TestListInState:
    async def test_filters_to_running_only(self, repo, db_service):
        a = await db_service.create_todo_item("a", "")
        b = await db_service.create_todo_item("b", "")
        c = await db_service.create_todo_item("c", "")
        # Move 'a' to RUNNING; b and c stay in BACKLOG
        await db_service.update_item(a["id"], column_name="doing", status="running")

        running = await repo.list_in_state(ItemState.RUNNING)
        backlog = await repo.list_in_state(ItemState.BACKLOG)

        assert {i["id"] for i in running} == {a["id"]}
        assert {i["id"] for i in backlog} == {b["id"], c["id"]}

    async def test_list_running_alias(self, repo, db_service):
        a = await db_service.create_todo_item("a", "")
        await db_service.update_item(a["id"], column_name="doing", status="running")
        assert {i["id"] for i in await repo.list_running()} == {a["id"]}


class TestListQueued:
    async def test_returns_queued_in_position_order(self, repo, db_service):
        a = await db_service.create_todo_item("a", "")
        b = await db_service.create_todo_item("b", "")
        # Place both in QUEUED with explicit positions to assert ordering
        await db_service.update_item(a["id"], column_name="doing", status="queued", position=1)
        await db_service.update_item(b["id"], column_name="doing", status="queued", position=0)

        queued = await repo.list_queued(limit=10)
        # Position 0 should come first
        assert [i["id"] for i in queued] == [b["id"], a["id"]]

    async def test_respects_limit(self, repo, db_service):
        for i in range(3):
            it = await db_service.create_todo_item(f"x{i}", "")
            await db_service.update_item(it["id"], column_name="doing", status="queued")
        assert len(await repo.list_queued(limit=2)) == 2


class TestTransition:
    async def test_basic_transition_writes_canonical_encoding(self, repo, db_service):
        item = await db_service.create_todo_item("X", "")
        result = await repo.transition(item["id"], Event.START)
        assert result["column_name"] == "doing"
        assert result["status"] == "running"

    async def test_extra_fields_are_persisted(self, repo, db_service):
        item = await db_service.create_todo_item("X", "")
        result = await repo.transition(
            item["id"], Event.START,
            session_id="sess-1", branch_name="agent/x",
        )
        assert result["session_id"] == "sess-1"
        assert result["branch_name"] == "agent/x"
        assert result["column_name"] == "doing"
        assert result["status"] == "running"

    async def test_illegal_transition_raises(self, repo, db_service):
        item = await db_service.create_todo_item("X", "")
        await db_service.update_item(item["id"], column_name="done", status=None)
        with pytest.raises(InvalidTransition):
            await repo.transition(item["id"], Event.PAUSE)

    async def test_missing_item_raises(self, repo):
        with pytest.raises(ItemNotFound):
            await repo.transition("nope", Event.START)


class TestUpdateFields:
    async def test_writes_non_state_fields(self, repo, db_service):
        item = await db_service.create_todo_item("X", "")
        result = await repo.update_fields(item["id"], session_id="sess-x")
        assert result["session_id"] == "sess-x"
        # State unchanged
        assert result["column_name"] == "todo"

    async def test_rejects_column_name(self, repo, db_service):
        item = await db_service.create_todo_item("X", "")
        with pytest.raises(ValueError, match="transition"):
            await repo.update_fields(item["id"], column_name="doing")

    async def test_rejects_status(self, repo, db_service):
        item = await db_service.create_todo_item("X", "")
        with pytest.raises(ValueError, match="transition"):
            await repo.update_fields(item["id"], status="running")

    async def test_rejects_unknown_field(self, repo, db_service):
        item = await db_service.create_todo_item("X", "")
        with pytest.raises(ValueError, match="unknown item field"):
            await repo.update_fields(item["id"], not_a_real_column="bad")

    async def test_rejects_start_copy(self, repo, db_service):
        # `start_copy` is on the items table but is intentionally not in
        # the writable set — it's an init-only flag set at create time.
        item = await db_service.create_todo_item("X", "")
        with pytest.raises(ValueError, match="unknown item field"):
            await repo.update_fields(item["id"], start_copy=1)


class TestTransitionFieldValidation:
    async def test_rejects_unknown_extra_field(self, repo, db_service):
        item = await db_service.create_todo_item("X", "")
        with pytest.raises(ValueError, match="unknown item field"):
            await repo.transition(item["id"], Event.START, not_a_real_column="bad")


class TestMoveToColumn:
    async def test_cross_column_move_clears_status(self, repo, db_service):
        # Item starts CANCELLED; user drags it to "doing" column.
        # Before the fix, this would have produced ("doing", "cancelled") —
        # an off-canon encoding. The repo must clear status to land at
        # ("doing", None), the SM-fallback for BACKLOG.
        item = await db_service.create_todo_item("X", "")
        await db_service.update_item(item["id"], column_name="todo", status="cancelled")
        moved = await repo.move_to_column(item["id"], "doing", 0)
        assert moved["column_name"] == "doing"
        assert moved["status"] is None

    async def test_within_column_move_preserves_status(self, repo, db_service):
        # Reordering within a column shouldn't touch status — the agent
        # might be RUNNING, the user is just rearranging cards.
        item = await db_service.create_todo_item("X", "")
        await db_service.update_item(item["id"], column_name="doing", status="running")
        moved = await repo.move_to_column(item["id"], "doing", 5)
        assert moved["column_name"] == "doing"
        assert moved["status"] == "running"
        assert moved["position"] == 5

    async def test_move_to_done_clears_worktree(self, repo, db_service):
        item = await db_service.create_todo_item("X", "")
        await db_service.update_item(
            item["id"], column_name="review", status=None,
            worktree_path="/tmp/wt", branch_name="agent/x",
        )
        moved = await repo.move_to_column(item["id"], "done", 0)
        assert moved["worktree_path"] is None

    async def test_move_to_archive_preserves_done_at(self, repo, db_service):
        item = await db_service.create_todo_item("X", "")
        await db_service.update_item(
            item["id"], column_name="done", status=None,
            done_at="2025-01-15T10:00:00",
        )
        moved = await repo.move_to_column(item["id"], "archive", 0)
        # The archive carry-forward preserves the existing done_at.
        assert moved["done_at"] == "2025-01-15T10:00:00"

    async def test_move_to_archive_sets_done_at_when_missing(self, repo, db_service):
        # Edge case: dragging an item with no done_at directly to archive —
        # the move acts as a "completion" event for timestamp purposes.
        item = await db_service.create_todo_item("X", "")
        moved = await repo.move_to_column(item["id"], "archive", 0)
        assert moved["done_at"] is not None

    async def test_resulting_encoding_is_readable_by_sm(self, repo, db_service):
        # End-to-end: cross-column DnD followed by a state read shouldn't
        # raise — either the encoding is canonical or the fallback covers it.
        from src.domain.item_state import from_columns
        item = await db_service.create_todo_item("X", "")
        await db_service.update_item(item["id"], column_name="todo", status="cancelled")
        moved = await repo.move_to_column(item["id"], "doing", 0)
        # SM read of the post-DnD encoding must succeed.
        from_columns(moved["column_name"], moved.get("status"))


class TestShiftPositions:
    async def test_shifts_only_at_or_after_threshold(self, repo, db_service):
        a = await db_service.create_todo_item("a", "")  # position 0
        b = await db_service.create_todo_item("b", "")  # position 1
        c = await db_service.create_todo_item("c", "")  # position 2

        # Shift positions >= 1 in "todo", excluding b (the inserter).
        await repo.shift_positions("todo", 1, b["id"])

        # `list_all` returns a partial column projection without position;
        # `get` returns the full row.
        a_after = await repo.get(a["id"])
        b_after = await repo.get(b["id"])
        c_after = await repo.get(c["id"])
        assert a_after["position"] == 0  # below threshold, unchanged
        assert b_after["position"] == 1  # excluded, unchanged
        assert c_after["position"] == 3  # shifted from 2 to 3
