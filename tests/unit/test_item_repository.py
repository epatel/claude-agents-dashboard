"""Tests for src/repositories/item_repository.py."""

import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

from src.database import Database
from src.domain.item_state import ItemState
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
