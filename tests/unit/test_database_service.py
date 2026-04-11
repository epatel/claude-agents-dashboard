"""Unit tests for DatabaseService uncovered methods."""

import json
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

from src.database import Database
from src.services.database_service import DatabaseService
from src.agent.session import AgentResult


@pytest_asyncio.fixture
async def db():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        database = Database(db_path)
        await database.initialize()
        yield database


@pytest_asyncio.fixture
async def db_service(db):
    return DatabaseService(db)


@pytest_asyncio.fixture
async def item(db_service):
    """Create a base item for use in tests."""
    return await db_service.create_todo_item("Base Item", "A base item for testing")


# ---------------------------------------------------------------------------
# copy_item
# ---------------------------------------------------------------------------

class TestCopyItem:
    async def test_copy_creates_new_item(self, db_service, item):
        copied = await db_service.copy_item(item["id"])
        assert copied["id"] != item["id"]
        assert copied["title"] == item["title"]
        assert copied["description"] == item["description"]
        assert copied["column_name"] == "todo"

    async def test_copy_inherits_model(self, db_service):
        await db_service.create_todo_item("Modeled", "desc")
        async with db_service.db.connect() as conn:
            await conn.execute(
                "INSERT INTO items (id, title, description, column_name, position, model) VALUES (?, ?, ?, 'todo', 99, ?)",
                ("item-model", "Modeled", "desc", "claude-3-5-sonnet"),
            )
            await conn.commit()
        copied = await db_service.copy_item("item-model")
        assert copied["model"] == "claude-3-5-sonnet"

    async def test_copy_nonexistent_item_raises(self, db_service):
        with pytest.raises(ValueError, match="not found"):
            await db_service.copy_item("does-not-exist")

    async def test_copy_gets_next_position(self, db_service, item):
        copy1 = await db_service.copy_item(item["id"])
        copy2 = await db_service.copy_item(item["id"])
        assert copy2["position"] > copy1["position"]


# ---------------------------------------------------------------------------
# store_clarification / update_clarification_response
# ---------------------------------------------------------------------------

class TestClarification:
    async def test_store_clarification_with_choices(self, db_service, item):
        await db_service.store_clarification(item["id"], "Which approach?", ["A", "B"])
        async with db_service.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT prompt, choices FROM clarifications WHERE item_id = ?", (item["id"],)
            )
            row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "Which approach?"
        assert json.loads(row[1]) == ["A", "B"]

    async def test_store_clarification_without_choices(self, db_service, item):
        await db_service.store_clarification(item["id"], "What do you mean?", None)
        async with db_service.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT choices FROM clarifications WHERE item_id = ?", (item["id"],)
            )
            row = await cursor.fetchone()
        assert row[0] is None

    async def test_update_clarification_response(self, db_service, item):
        await db_service.store_clarification(item["id"], "Q?", None)
        await db_service.update_clarification_response(item["id"], "User answer")
        async with db_service.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT response, answered_at FROM clarifications WHERE item_id = ?", (item["id"],)
            )
            row = await cursor.fetchone()
        assert row[0] == "User answer"
        assert row[1] is not None

    async def test_update_clarification_only_updates_unanswered(self, db_service, item):
        await db_service.store_clarification(item["id"], "Q1?", None)
        await db_service.update_clarification_response(item["id"], "First answer")
        # Calling again should not overwrite (WHERE response IS NULL guard)
        await db_service.update_clarification_response(item["id"], "Second answer")
        async with db_service.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT response FROM clarifications WHERE item_id = ?", (item["id"],)
            )
            row = await cursor.fetchone()
        assert row[0] == "First answer"


# ---------------------------------------------------------------------------
# store_review_comments
# ---------------------------------------------------------------------------

class TestStoreReviewComments:
    async def test_stores_multiple_comments(self, db_service, item):
        await db_service.store_review_comments(item["id"], ["Comment 1", "Comment 2", "Comment 3"])
        async with db_service.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT content FROM review_comments WHERE item_id = ? ORDER BY created_at", (item["id"],)
            )
            rows = await cursor.fetchall()
        assert len(rows) == 3
        assert rows[0][0] == "Comment 1"
        assert rows[2][0] == "Comment 3"

    async def test_stores_empty_list(self, db_service, item):
        await db_service.store_review_comments(item["id"], [])
        async with db_service.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM review_comments WHERE item_id = ?", (item["id"],)
            )
            row = await cursor.fetchone()
        assert row[0] == 0


# ---------------------------------------------------------------------------
# save_token_usage
# ---------------------------------------------------------------------------

class TestSaveTokenUsage:
    async def test_saves_token_usage(self, db_service, item):
        result = AgentResult(
            success=True,
            session_id="sess-abc",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            cost_usd=0.005,
        )
        await db_service.save_token_usage(item["id"], result)
        async with db_service.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT session_id, input_tokens, output_tokens, total_tokens, cost_usd"
                " FROM token_usage WHERE item_id = ?",
                (item["id"],),
            )
            row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "sess-abc"
        assert row[1] == 100
        assert row[2] == 50
        assert row[3] == 150
        assert abs(row[4] - 0.005) < 1e-9

    async def test_skips_empty_token_usage(self, db_service, item):
        result = AgentResult(
            success=True,
            session_id=None,
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
            cost_usd=None,
        )
        await db_service.save_token_usage(item["id"], result)
        async with db_service.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM token_usage WHERE item_id = ?", (item["id"],)
            )
            row = await cursor.fetchone()
        assert row[0] == 0

    async def test_saves_partial_token_usage(self, db_service, item):
        """Even a single non-None/non-zero value should trigger a save."""
        result = AgentResult(success=True, input_tokens=10)
        await db_service.save_token_usage(item["id"], result)
        async with db_service.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM token_usage WHERE item_id = ?", (item["id"],)
            )
            row = await cursor.fetchone()
        assert row[0] == 1


# ---------------------------------------------------------------------------
# save_allowed_command
# ---------------------------------------------------------------------------

class TestSaveAllowedCommand:
    async def test_adds_command(self, db_service):
        result = await db_service.save_allowed_command("flutter")
        assert "flutter" in result

    async def test_deduplicates_command(self, db_service):
        await db_service.save_allowed_command("flutter")
        result = await db_service.save_allowed_command("flutter")
        assert result.count("flutter") == 1

    async def test_accumulates_commands(self, db_service):
        await db_service.save_allowed_command("flutter")
        await db_service.save_allowed_command("dart")
        result = await db_service.save_allowed_command("npm")
        assert set(result) == {"flutter", "dart", "npm"}

    async def test_persists_to_db(self, db_service):
        await db_service.save_allowed_command("make")
        config = await db_service.get_agent_config()
        commands = json.loads(config["allowed_commands"])
        assert "make" in commands


# ---------------------------------------------------------------------------
# save_allowed_builtin_tool
# ---------------------------------------------------------------------------

class TestSaveAllowedBuiltinTool:
    async def test_adds_tool(self, db_service):
        result = await db_service.save_allowed_builtin_tool("WebSearch")
        assert "WebSearch" in result

    async def test_deduplicates_tool(self, db_service):
        await db_service.save_allowed_builtin_tool("WebSearch")
        result = await db_service.save_allowed_builtin_tool("WebSearch")
        assert result.count("WebSearch") == 1

    async def test_accumulates_tools(self, db_service):
        await db_service.save_allowed_builtin_tool("WebSearch")
        result = await db_service.save_allowed_builtin_tool("WebFetch")
        assert set(result) == {"WebSearch", "WebFetch"}

    async def test_persists_to_db(self, db_service):
        await db_service.save_allowed_builtin_tool("WebFetch")
        config = await db_service.get_agent_config()
        tools = json.loads(config["allowed_builtin_tools"])
        assert "WebFetch" in tools


# ---------------------------------------------------------------------------
# delete_item_and_related
# ---------------------------------------------------------------------------

class TestDeleteItemAndRelated:
    async def test_deletes_item(self, db_service, item):
        deleted = await db_service.delete_item_and_related(item["id"])
        assert deleted["id"] == item["id"]
        remaining = await db_service.get_item(item["id"])
        assert remaining is None

    async def test_deletes_work_log_entries(self, db_service, item):
        await db_service.log_entry(item["id"], "info", "Some log line")
        await db_service.delete_item_and_related(item["id"])
        async with db_service.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM work_log WHERE item_id = ?", (item["id"],)
            )
            row = await cursor.fetchone()
        assert row[0] == 0

    async def test_deletes_clarifications(self, db_service, item):
        await db_service.store_clarification(item["id"], "Q?", None)
        await db_service.delete_item_and_related(item["id"])
        async with db_service.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM clarifications WHERE item_id = ?", (item["id"],)
            )
            row = await cursor.fetchone()
        assert row[0] == 0

    async def test_deletes_review_comments(self, db_service, item):
        await db_service.store_review_comments(item["id"], ["comment"])
        await db_service.delete_item_and_related(item["id"])
        async with db_service.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM review_comments WHERE item_id = ?", (item["id"],)
            )
            row = await cursor.fetchone()
        assert row[0] == 0

    async def test_deletes_dependencies(self, db_service):
        item_a = await db_service.create_todo_item("A", "")
        item_b = await db_service.create_todo_item("B", "")
        await db_service.set_item_dependencies(item_b["id"], [item_a["id"]])
        await db_service.delete_item_and_related(item_a["id"])
        async with db_service.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM item_dependencies WHERE item_id = ? OR requires_item_id = ?",
                (item_a["id"], item_a["id"]),
            )
            row = await cursor.fetchone()
        assert row[0] == 0

    async def test_returns_none_for_nonexistent_item(self, db_service):
        result = await db_service.delete_item_and_related("ghost-item")
        assert result is None


# ---------------------------------------------------------------------------
# Dependency methods
# ---------------------------------------------------------------------------

class TestDependencies:
    async def test_get_item_dependencies_empty(self, db_service, item):
        deps = await db_service.get_item_dependencies(item["id"])
        assert deps == []

    async def test_set_and_get_item_dependencies(self, db_service):
        item_a = await db_service.create_todo_item("A", "")
        item_b = await db_service.create_todo_item("B", "")
        deps = await db_service.set_item_dependencies(item_b["id"], [item_a["id"]])
        assert len(deps) == 1
        assert deps[0]["id"] == item_a["id"]
        assert deps[0]["title"] == "A"

    async def test_set_dependencies_replaces_existing(self, db_service):
        item_a = await db_service.create_todo_item("A", "")
        item_b = await db_service.create_todo_item("B", "")
        item_c = await db_service.create_todo_item("C", "")
        await db_service.set_item_dependencies(item_c["id"], [item_a["id"]])
        deps = await db_service.set_item_dependencies(item_c["id"], [item_b["id"]])
        assert len(deps) == 1
        assert deps[0]["id"] == item_b["id"]

    async def test_set_dependencies_self_referential_raises(self, db_service, item):
        with pytest.raises(ValueError, match="cannot depend on itself"):
            await db_service.set_item_dependencies(item["id"], [item["id"]])

    async def test_set_dependencies_nonexistent_raises(self, db_service, item):
        with pytest.raises(ValueError, match="not found"):
            await db_service.set_item_dependencies(item["id"], ["ghost-id"])

    async def test_set_dependencies_empty_clears_all(self, db_service):
        item_a = await db_service.create_todo_item("A", "")
        item_b = await db_service.create_todo_item("B", "")
        await db_service.set_item_dependencies(item_b["id"], [item_a["id"]])
        deps = await db_service.set_item_dependencies(item_b["id"], [])
        assert deps == []

    async def test_is_item_blocked_true(self, db_service):
        item_a = await db_service.create_todo_item("A", "")
        item_b = await db_service.create_todo_item("B", "")
        await db_service.set_item_dependencies(item_b["id"], [item_a["id"]])
        assert await db_service.is_item_blocked(item_b["id"]) is True

    async def test_is_item_blocked_false_when_no_deps(self, db_service, item):
        assert await db_service.is_item_blocked(item["id"]) is False

    async def test_is_item_blocked_false_when_dep_done(self, db_service):
        item_a = await db_service.create_todo_item("A", "")
        item_b = await db_service.create_todo_item("B", "")
        await db_service.set_item_dependencies(item_b["id"], [item_a["id"]])
        await db_service.update_item(item_a["id"], column_name="done")
        assert await db_service.is_item_blocked(item_b["id"]) is False

    async def test_get_blocking_items(self, db_service):
        item_a = await db_service.create_todo_item("A", "")
        item_b = await db_service.create_todo_item("B", "")
        await db_service.set_item_dependencies(item_b["id"], [item_a["id"]])
        blocking = await db_service.get_blocking_items(item_b["id"])
        assert len(blocking) == 1
        assert blocking[0]["id"] == item_a["id"]

    async def test_get_blocking_items_empty_when_dep_archived(self, db_service):
        item_a = await db_service.create_todo_item("A", "")
        item_b = await db_service.create_todo_item("B", "")
        await db_service.set_item_dependencies(item_b["id"], [item_a["id"]])
        await db_service.update_item(item_a["id"], column_name="archive")
        blocking = await db_service.get_blocking_items(item_b["id"])
        assert blocking == []

    async def test_get_dependent_items(self, db_service):
        item_a = await db_service.create_todo_item("A", "")
        item_b = await db_service.create_todo_item("B", "")
        item_c = await db_service.create_todo_item("C", "")
        await db_service.set_item_dependencies(item_b["id"], [item_a["id"]])
        await db_service.set_item_dependencies(item_c["id"], [item_a["id"]])
        dependents = await db_service.get_dependent_items(item_a["id"])
        assert set(dependents) == {item_b["id"], item_c["id"]}

    async def test_get_dependent_items_empty(self, db_service, item):
        result = await db_service.get_dependent_items(item["id"])
        assert result == []

    async def test_get_all_blocked_status(self, db_service):
        item_a = await db_service.create_todo_item("A", "")
        item_b = await db_service.create_todo_item("B", "")
        await db_service.set_item_dependencies(item_b["id"], [item_a["id"]])
        blocked = await db_service.get_all_blocked_status()
        assert item_b["id"] in blocked
        assert any(b["id"] == item_a["id"] for b in blocked[item_b["id"]])

    async def test_get_all_blocked_status_excludes_done_deps(self, db_service):
        item_a = await db_service.create_todo_item("A", "")
        item_b = await db_service.create_todo_item("B", "")
        await db_service.set_item_dependencies(item_b["id"], [item_a["id"]])
        await db_service.update_item(item_a["id"], column_name="done")
        blocked = await db_service.get_all_blocked_status()
        assert item_b["id"] not in blocked

    async def test_get_all_blocked_status_empty_when_no_deps(self, db_service):
        await db_service.create_todo_item("Standalone", "")
        blocked = await db_service.get_all_blocked_status()
        assert blocked == {}


# ---------------------------------------------------------------------------
# has_file_changes column
# ---------------------------------------------------------------------------

class TestHasFileChanges:
    async def test_update_item_with_has_file_changes(self, db_service, item):
        updated = await db_service.update_item(item["id"], has_file_changes=1)
        assert updated["has_file_changes"] == 1

    async def test_has_file_changes_defaults_to_none(self, db_service, item):
        fetched = await db_service.get_item(item["id"])
        assert fetched["has_file_changes"] is None

    async def test_has_file_changes_zero_means_no_changes(self, db_service, item):
        updated = await db_service.update_item(item["id"], has_file_changes=0)
        assert updated["has_file_changes"] == 0

    async def test_has_file_changes_set_with_review_column(self, db_service, item):
        updated = await db_service.update_item(
            item["id"], column_name="review", has_file_changes=1
        )
        assert updated["column_name"] == "review"
        assert updated["has_file_changes"] == 1

    async def test_has_file_changes_preserved_on_other_update(self, db_service, item):
        await db_service.update_item(item["id"], has_file_changes=1)
        updated = await db_service.update_item(item["id"], status="some_status")
        assert updated["has_file_changes"] == 1


# ---------------------------------------------------------------------------
# start_copy column
# ---------------------------------------------------------------------------

class TestStartCopyColumn:
    async def test_start_copy_defaults_to_zero(self, db_service, item):
        fetched = await db_service.get_item(item["id"])
        assert fetched["start_copy"] == 0

    async def test_start_copy_set_at_creation(self, db_service):
        """start_copy is set via INSERT at creation, not via update_item."""
        async with db_service.db.connect() as conn:
            await conn.execute(
                "INSERT INTO items (id, title, description, column_name, position, start_copy) "
                "VALUES (?, ?, ?, 'todo', 0, 1)",
                ("item-sc", "Start Copy Item", "desc"),
            )
            await conn.commit()
        fetched = await db_service.get_item("item-sc")
        assert fetched["start_copy"] == 1

    async def test_start_copy_not_in_update_allowed_columns(self, db_service, item):
        """start_copy is not updatable via update_item."""
        with pytest.raises(ValueError, match="Invalid item column"):
            await db_service.update_item(item["id"], start_copy=1)


# ---------------------------------------------------------------------------
# update_item invalid column guard
# ---------------------------------------------------------------------------

class TestUpdateItemValidation:
    async def test_invalid_column_raises(self, db_service, item):
        with pytest.raises(ValueError, match="Invalid item column"):
            await db_service.update_item(item["id"], not_a_real_column="bad")

    async def test_done_at_auto_set_on_done(self, db_service, item):
        updated = await db_service.update_item(item["id"], column_name="done")
        assert updated["done_at"] is not None

    async def test_done_at_cleared_on_leave_done(self, db_service, item):
        await db_service.update_item(item["id"], column_name="done")
        updated = await db_service.update_item(item["id"], column_name="todo")
        assert updated["done_at"] is None


# ---------------------------------------------------------------------------
# update_epic invalid column guard
# ---------------------------------------------------------------------------

class TestUpdateEpicValidation:
    async def test_invalid_epic_column_raises(self, db_service):
        epic = await db_service.create_epic("Test", "red")
        with pytest.raises(ValueError, match="Invalid epic column"):
            await db_service.update_epic(epic["id"], invalid_field="nope")
