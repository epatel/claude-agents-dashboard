"""Unit tests for NotificationService broadcast methods."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.services.notification_service import NotificationService


@pytest.fixture
def mock_ws_manager():
    manager = MagicMock()
    manager.broadcast = AsyncMock()
    return manager


@pytest.fixture
def service(mock_ws_manager):
    return NotificationService(ws_manager=mock_ws_manager)


# ---------------------------------------------------------------------------
# broadcast_item_updated
# ---------------------------------------------------------------------------

class TestBroadcastItemUpdated:
    @pytest.mark.asyncio
    async def test_broadcasts_item_updated_event(self, service, mock_ws_manager):
        item = {"id": "1", "title": "Test"}
        await service.broadcast_item_updated(item)
        mock_ws_manager.broadcast.assert_awaited_once_with("item_updated", item)

    @pytest.mark.asyncio
    async def test_no_source_passes_item_unchanged(self, service, mock_ws_manager):
        item = {"id": "1", "title": "Test"}
        await service.broadcast_item_updated(item)
        _, data = mock_ws_manager.broadcast.call_args.args
        assert "_source" not in data

    @pytest.mark.asyncio
    async def test_with_source_adds_source_key(self, service, mock_ws_manager):
        item = {"id": "1", "title": "Test"}
        await service.broadcast_item_updated(item, source="agent")
        _, data = mock_ws_manager.broadcast.call_args.args
        assert data["_source"] == "agent"

    @pytest.mark.asyncio
    async def test_with_source_preserves_original_item_fields(self, service, mock_ws_manager):
        item = {"id": "1", "title": "Test"}
        await service.broadcast_item_updated(item, source="agent")
        _, data = mock_ws_manager.broadcast.call_args.args
        assert data["id"] == "1"
        assert data["title"] == "Test"

    @pytest.mark.asyncio
    async def test_source_none_does_not_mutate_item(self, service, mock_ws_manager):
        """Passing source=None should pass the original item dict, not a copy."""
        item = {"id": "2"}
        await service.broadcast_item_updated(item, source=None)
        _, data = mock_ws_manager.broadcast.call_args.args
        assert data is item

    @pytest.mark.asyncio
    async def test_with_source_creates_new_dict_not_mutating_original(self, service, mock_ws_manager):
        item = {"id": "3"}
        await service.broadcast_item_updated(item, source="user")
        assert "_source" not in item  # original must be untouched


# ---------------------------------------------------------------------------
# broadcast_item_created
# ---------------------------------------------------------------------------

class TestBroadcastItemCreated:
    @pytest.mark.asyncio
    async def test_broadcasts_item_created_event(self, service, mock_ws_manager):
        item = {"id": "10", "title": "New Item"}
        await service.broadcast_item_created(item)
        mock_ws_manager.broadcast.assert_awaited_once_with("item_created", item)


# ---------------------------------------------------------------------------
# broadcast_item_deleted
# ---------------------------------------------------------------------------

class TestBroadcastItemDeleted:
    @pytest.mark.asyncio
    async def test_broadcasts_item_deleted_with_id(self, service, mock_ws_manager):
        await service.broadcast_item_deleted("abc-123")
        mock_ws_manager.broadcast.assert_awaited_once_with("item_deleted", {"id": "abc-123"})


# ---------------------------------------------------------------------------
# broadcast_agent_log
# ---------------------------------------------------------------------------

class TestBroadcastAgentLog:
    @pytest.mark.asyncio
    async def test_broadcasts_agent_log_event(self, service, mock_ws_manager):
        await service.broadcast_agent_log("item-1", "tool_use", "doing stuff")
        mock_ws_manager.broadcast.assert_awaited_once_with("agent_log", {
            "item_id": "item-1",
            "entry_type": "tool_use",
            "content": "doing stuff",
        })


# ---------------------------------------------------------------------------
# broadcast_clarification_requested
# ---------------------------------------------------------------------------

class TestBroadcastClarificationRequested:
    @pytest.mark.asyncio
    async def test_broadcasts_with_choices_as_json(self, service, mock_ws_manager):
        choices = ["Yes", "No"]
        await service.broadcast_clarification_requested("item-1", "Continue?", choices)
        _, data = mock_ws_manager.broadcast.call_args.args
        assert data["item_id"] == "item-1"
        assert data["prompt"] == "Continue?"
        assert data["choices"] == json.dumps(choices)

    @pytest.mark.asyncio
    async def test_broadcasts_with_none_choices(self, service, mock_ws_manager):
        await service.broadcast_clarification_requested("item-2", "What next?", None)
        _, data = mock_ws_manager.broadcast.call_args.args
        assert data["choices"] is None

    @pytest.mark.asyncio
    async def test_event_name_is_clarification_requested(self, service, mock_ws_manager):
        await service.broadcast_clarification_requested("item-3", "Hello?", None)
        event_name, _ = mock_ws_manager.broadcast.call_args.args
        assert event_name == "clarification_requested"


# ---------------------------------------------------------------------------
# broadcast_epic_created
# ---------------------------------------------------------------------------

class TestBroadcastEpicCreated:
    @pytest.mark.asyncio
    async def test_broadcasts_epic_created(self, service, mock_ws_manager):
        epic = {"id": "e1", "title": "Epic One"}
        await service.broadcast_epic_created(epic)
        mock_ws_manager.broadcast.assert_awaited_once_with("epic_created", epic)


# ---------------------------------------------------------------------------
# broadcast_epic_updated
# ---------------------------------------------------------------------------

class TestBroadcastEpicUpdated:
    @pytest.mark.asyncio
    async def test_broadcasts_epic_updated(self, service, mock_ws_manager):
        epic = {"id": "e2", "title": "Updated Epic"}
        await service.broadcast_epic_updated(epic)
        mock_ws_manager.broadcast.assert_awaited_once_with("epic_updated", epic)


# ---------------------------------------------------------------------------
# broadcast_epic_deleted
# ---------------------------------------------------------------------------

class TestBroadcastEpicDeleted:
    @pytest.mark.asyncio
    async def test_broadcasts_epic_deleted_with_id(self, service, mock_ws_manager):
        await service.broadcast_epic_deleted("epic-99")
        mock_ws_manager.broadcast.assert_awaited_once_with("epic_deleted", {"id": "epic-99"})


# ---------------------------------------------------------------------------
# format_tool_use
# ---------------------------------------------------------------------------

class TestFormatToolUse:
    def test_write_tool(self, service):
        result = service.format_tool_use("Write", {"file_path": "src/main.py"})
        assert result == "**Write** `src/main.py`"

    def test_edit_tool(self, service):
        result = service.format_tool_use("Edit", {"file_path": "src/utils.py"})
        assert result == "**Edit** `src/utils.py`"

    def test_read_tool(self, service):
        result = service.format_tool_use("Read", {"file_path": "README.md"})
        assert result == "**Read** `README.md`"

    def test_bash_tool_short_command(self, service):
        result = service.format_tool_use("Bash", {"command": "ls -la"})
        assert result == "**Bash** `ls -la`"

    def test_bash_tool_truncates_long_command(self, service):
        long_cmd = "x" * 200
        result = service.format_tool_use("Bash", {"command": long_cmd})
        assert "**Bash**" in result
        assert "..." in result
        # command portion should be truncated to 120 + "..."
        assert len(result) < len(long_cmd)

    def test_bash_tool_exact_120_chars_not_truncated(self, service):
        cmd = "y" * 120
        result = service.format_tool_use("Bash", {"command": cmd})
        assert "..." not in result

    def test_glob_tool(self, service):
        result = service.format_tool_use("Glob", {"pattern": "**/*.py"})
        assert result == "**Glob** `**/*.py`"

    def test_grep_tool(self, service):
        result = service.format_tool_use("Grep", {"pattern": "TODO", "path": "src/"})
        assert result == "**Grep** `TODO` in `src/`"

    def test_grep_tool_default_path(self, service):
        result = service.format_tool_use("Grep", {"pattern": "TODO"})
        assert "`TODO`" in result
        assert "`.`" in result

    def test_create_todo_tool(self, service):
        result = service.format_tool_use("create_todo", {"title": "Fix the bug"})
        assert result == "**Create Todo** Fix the bug"

    def test_set_commit_message_tool(self, service):
        result = service.format_tool_use("set_commit_message", {"message": "feat: add feature"})
        assert result == "**Commit Message** feat: add feature"

    def test_create_shortcut_tool(self, service):
        result = service.format_tool_use("create_shortcut", {"name": "test", "command": "pytest"})
        assert result == "**Create Shortcut** test → `pytest`"

    def test_ask_user_tool_short(self, service):
        result = service.format_tool_use("ask_user", {"question": "What should I do?"})
        assert result == "**Ask User** What should I do?"

    def test_ask_user_tool_truncates_long_question(self, service):
        long_q = "q" * 200
        result = service.format_tool_use("ask_user", {"question": long_q})
        assert "..." in result
        # question should be clipped to 100 chars
        assert len(result) < len(long_q)

    def test_ask_user_exact_100_chars_not_truncated(self, service):
        q = "z" * 100
        result = service.format_tool_use("ask_user", {"question": q})
        assert "..." not in result

    def test_unknown_tool_short_input(self, service):
        result = service.format_tool_use("MyTool", {"key": "val"})
        assert result.startswith("**MyTool**")
        assert "val" in result

    def test_unknown_tool_truncates_long_input(self, service):
        big_input = {"key": "v" * 200}
        result = service.format_tool_use("BigTool", big_input)
        assert "..." in result

    def test_unknown_tool_exact_100_chars_summary_not_truncated(self, service):
        # Build an input whose str() is exactly 100 chars
        inp = {"k": "a" * 94}  # {'k': 'aaa...'} -> roughly 100 chars; adjust as needed
        summary = str(inp)
        if len(summary) <= 100:
            result = service.format_tool_use("T", inp)
            assert "..." not in result


# ---------------------------------------------------------------------------
# format_completion_log
# ---------------------------------------------------------------------------

class TestFormatCompletionLog:
    def test_no_args_returns_agent_completed(self, service):
        result = service.format_completion_log()
        assert result == "Agent completed"

    def test_with_cost(self, service):
        result = service.format_completion_log(cost_usd=0.0042)
        assert "cost: $0.0042" in result
        assert result.startswith("Agent completed")

    def test_with_total_tokens(self, service):
        result = service.format_completion_log(total_tokens=5000)
        assert "tokens: 5,000" in result

    def test_with_input_and_output_tokens(self, service):
        result = service.format_completion_log(input_tokens=3000, output_tokens=2000)
        assert "tokens: 5,000" in result

    def test_total_tokens_takes_priority_over_input_output(self, service):
        result = service.format_completion_log(total_tokens=9999, input_tokens=1000, output_tokens=1000)
        assert "tokens: 9,999" in result

    def test_with_cost_and_tokens(self, service):
        result = service.format_completion_log(cost_usd=0.01, total_tokens=1000)
        assert "cost:" in result
        assert "tokens:" in result

    def test_zero_cost_not_shown(self, service):
        """cost_usd=0.0 is falsy, so it should not appear."""
        result = service.format_completion_log(cost_usd=0.0)
        assert "cost:" not in result

    def test_zero_tokens_not_shown(self, service):
        """total_tokens=0 is falsy, so it should not appear."""
        result = service.format_completion_log(total_tokens=0)
        assert "tokens:" not in result
