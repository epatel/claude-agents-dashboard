"""Tests for src/repositories/epic_repository.py."""

import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

from src.database import Database
from src.repositories.epic_repository import EpicNotFound, EpicRepository
from src.services.database_service import DatabaseService


@pytest_asyncio.fixture
async def db():
    with tempfile.TemporaryDirectory() as d:
        database = Database(Path(d) / "test.db")
        await database.initialize()
        yield database


@pytest_asyncio.fixture
async def db_service(db):
    return DatabaseService(db)


@pytest_asyncio.fixture
async def repo(db_service):
    return EpicRepository(db_service)


class TestCreate:
    async def test_creates_with_position_assigned(self, repo):
        a = await repo.create("Alpha", "blue")
        b = await repo.create("Beta", "red")
        assert a["title"] == "Alpha"
        assert b["title"] == "Beta"
        assert a["position"] != b["position"]


class TestListAll:
    async def test_returns_all_in_position_order(self, repo):
        await repo.create("a", "blue")
        await repo.create("b", "red")
        all_epics = await repo.list_all()
        assert [e["title"] for e in all_epics] == ["a", "b"]


class TestGet:
    async def test_returns_epic_when_present(self, repo):
        epic = await repo.create("a", "blue")
        got = await repo.get(epic["id"])
        assert got is not None and got["id"] == epic["id"]

    async def test_returns_none_when_missing(self, repo):
        assert await repo.get("nope") is None


class TestUpdate:
    async def test_writes_known_fields(self, repo):
        epic = await repo.create("a", "blue")
        updated = await repo.update(epic["id"], title="renamed")
        assert updated["title"] == "renamed"

    async def test_rejects_unknown_field(self, repo):
        epic = await repo.create("a", "blue")
        with pytest.raises(ValueError, match="unknown epic field"):
            await repo.update(epic["id"], not_a_real_column="bad")

    async def test_raises_for_missing_epic(self, repo):
        with pytest.raises(EpicNotFound):
            await repo.update("nope", title="x")


class TestDelete:
    async def test_returns_deleted_row(self, repo):
        epic = await repo.create("a", "blue")
        deleted = await repo.delete(epic["id"])
        assert deleted["id"] == epic["id"]
        assert await repo.get(epic["id"]) is None

    async def test_raises_for_missing_epic(self, repo):
        with pytest.raises(EpicNotFound):
            await repo.delete("nope")
