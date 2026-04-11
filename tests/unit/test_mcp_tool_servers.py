"""Unit tests for MCP tool server factory functions.

Each module exposes a create_*_server() factory that returns an MCP server dict.
We patch create_sdk_mcp_server to capture the SdkMcpTool objects, then call
.handler(input_dict) directly to verify callback invocation and return values.
"""

import pytest
from unittest.mock import AsyncMock, patch


# ── Helpers ────────────────────────────────────────────────────────────

def capture_tools(module_path, factory_fn, *args, **kwargs):
    """Call factory_fn with args, patching create_sdk_mcp_server in module_path.

    Returns the list of SdkMcpTool objects passed to create_sdk_mcp_server.
    """
    captured = {}

    def fake_server(name, tools):
        captured["name"] = name
        captured["tools"] = tools
        return {}

    with patch(f"{module_path}.create_sdk_mcp_server", fake_server):
        factory_fn(*args, **kwargs)

    return captured


def get_tool(tools, name):
    """Return the tool with the given name, or raise KeyError."""
    for t in tools:
        if t.name == name:
            return t
    raise KeyError(f"Tool '{name}' not found. Available: {[t.name for t in tools]}")


# ── board_view ─────────────────────────────────────────────────────────

class TestBoardViewServer:
    def _make(self, cb):
        from src.agent.board_view import create_board_view_server
        return capture_tools("src.agent.board_view", create_board_view_server, cb)

    def test_server_name_is_board_view(self):
        cap = self._make(AsyncMock(return_value=""))
        assert cap["name"] == "board_view"

    def test_exposes_view_board_tool(self):
        cap = self._make(AsyncMock(return_value=""))
        tool = get_tool(cap["tools"], "view_board")
        assert tool.name == "view_board"

    def test_view_board_has_description(self):
        cap = self._make(AsyncMock(return_value=""))
        tool = get_tool(cap["tools"], "view_board")
        assert len(tool.description) > 0

    @pytest.mark.asyncio
    async def test_view_board_calls_callback_no_args(self):
        cb = AsyncMock(return_value="## Board\n- Todo: Fix bug")
        cap = self._make(cb)
        tool = get_tool(cap["tools"], "view_board")

        result = await tool.handler({})

        cb.assert_awaited_once_with()
        assert result["content"][0]["type"] == "text"
        assert result["content"][0]["text"] == "## Board\n- Todo: Fix bug"

    @pytest.mark.asyncio
    async def test_view_board_returns_callback_text(self):
        cb = AsyncMock(return_value="Empty board")
        cap = self._make(cb)
        tool = get_tool(cap["tools"], "view_board")

        result = await tool.handler({})
        assert result["content"][0]["text"] == "Empty board"

    def test_view_board_schema(self):
        from src.agent.board_view import VIEW_BOARD_SCHEMA
        assert VIEW_BOARD_SCHEMA["type"] == "object"
        assert VIEW_BOARD_SCHEMA["properties"] == {}


# ── shortcut ───────────────────────────────────────────────────────────

class TestShortcutServer:
    def _make(self, cb):
        from src.agent.shortcut import create_shortcut_server
        return capture_tools("src.agent.shortcut", create_shortcut_server, cb)

    def test_server_name_is_shortcut(self):
        cap = self._make(AsyncMock(return_value={"name": "x"}))
        assert cap["name"] == "shortcut"

    def test_exposes_create_shortcut_tool(self):
        cap = self._make(AsyncMock(return_value={"name": "x"}))
        tool = get_tool(cap["tools"], "create_shortcut")
        assert tool.name == "create_shortcut"

    @pytest.mark.asyncio
    async def test_create_shortcut_passes_name_and_command(self):
        cb = AsyncMock(return_value={"name": "Run tests"})
        cap = self._make(cb)
        tool = get_tool(cap["tools"], "create_shortcut")

        result = await tool.handler({"name": "Run tests", "command": "pytest"})

        cb.assert_awaited_once_with("Run tests", "pytest")
        assert result["content"][0]["type"] == "text"
        assert "Run tests" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_create_shortcut_uses_callback_name_in_response(self):
        cb = AsyncMock(return_value={"name": "Normalized Name"})
        cap = self._make(cb)
        tool = get_tool(cap["tools"], "create_shortcut")

        result = await tool.handler({"name": "raw name", "command": "npm test"})
        assert "Normalized Name" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_create_shortcut_missing_fields_default_empty(self):
        cb = AsyncMock(return_value={"name": ""})
        cap = self._make(cb)
        tool = get_tool(cap["tools"], "create_shortcut")

        await tool.handler({})
        cb.assert_awaited_once_with("", "")

    def test_schema_requires_name_and_command(self):
        from src.agent.shortcut import CREATE_SHORTCUT_SCHEMA
        assert "name" in CREATE_SHORTCUT_SCHEMA["required"]
        assert "command" in CREATE_SHORTCUT_SCHEMA["required"]


# ── tool_access ────────────────────────────────────────────────────────

class TestToolAccessServer:
    def _make(self, cb):
        from src.agent.tool_access import create_tool_access_server
        return capture_tools("src.agent.tool_access", create_tool_access_server, cb)

    def test_server_name_is_tool_access(self):
        cap = self._make(AsyncMock(return_value="approved"))
        assert cap["name"] == "tool_access"

    def test_exposes_request_tool_access_tool(self):
        cap = self._make(AsyncMock(return_value="approved"))
        tool = get_tool(cap["tools"], "request_tool_access")
        assert tool.name == "request_tool_access"

    @pytest.mark.asyncio
    async def test_approved_response(self):
        cb = AsyncMock(return_value="approved")
        cap = self._make(cb)
        tool = get_tool(cap["tools"], "request_tool_access")

        result = await tool.handler({"tool_name": "WebSearch", "reason": "Need to search docs"})

        cb.assert_awaited_once_with("WebSearch", "Need to search docs")
        assert result["content"][0]["text"] == "approved"

    @pytest.mark.asyncio
    async def test_denied_response(self):
        cb = AsyncMock(return_value="denied")
        cap = self._make(cb)
        tool = get_tool(cap["tools"], "request_tool_access")

        result = await tool.handler({"tool_name": "WebFetch", "reason": "Fetch a URL"})
        assert result["content"][0]["text"] == "denied"

    @pytest.mark.asyncio
    async def test_missing_fields_default_empty(self):
        cb = AsyncMock(return_value="denied")
        cap = self._make(cb)
        tool = get_tool(cap["tools"], "request_tool_access")

        await tool.handler({})
        cb.assert_awaited_once_with("", "")

    def test_schema_required_fields(self):
        from src.agent.tool_access import REQUEST_TOOL_ACCESS_SCHEMA
        assert "tool_name" in REQUEST_TOOL_ACCESS_SCHEMA["required"]
        assert "reason" in REQUEST_TOOL_ACCESS_SCHEMA["required"]


# ── command_access ─────────────────────────────────────────────────────

class TestCommandAccessServer:
    def _make(self, cb):
        from src.agent.command_access import create_command_access_server
        return capture_tools("src.agent.command_access", create_command_access_server, cb)

    def test_server_name_is_command_access(self):
        cap = self._make(AsyncMock(return_value="approved"))
        assert cap["name"] == "command_access"

    def test_exposes_request_command_access_tool(self):
        cap = self._make(AsyncMock(return_value="approved"))
        tool = get_tool(cap["tools"], "request_command_access")
        assert tool.name == "request_command_access"

    @pytest.mark.asyncio
    async def test_approved_response(self):
        cb = AsyncMock(return_value="approved")
        cap = self._make(cb)
        tool = get_tool(cap["tools"], "request_command_access")

        result = await tool.handler({"command": "flutter", "reason": "Build mobile app"})

        cb.assert_awaited_once_with("flutter", "Build mobile app")
        assert result["content"][0]["text"] == "approved"

    @pytest.mark.asyncio
    async def test_denied_response(self):
        cb = AsyncMock(return_value="denied")
        cap = self._make(cb)
        tool = get_tool(cap["tools"], "request_command_access")

        result = await tool.handler({"command": "rm", "reason": "Clean files"})
        assert result["content"][0]["text"] == "denied"

    @pytest.mark.asyncio
    async def test_missing_fields_default_empty(self):
        cb = AsyncMock(return_value="denied")
        cap = self._make(cb)
        tool = get_tool(cap["tools"], "request_command_access")

        await tool.handler({})
        cb.assert_awaited_once_with("", "")

    def test_schema_required_fields(self):
        from src.agent.command_access import REQUEST_COMMAND_ACCESS_SCHEMA
        assert "command" in REQUEST_COMMAND_ACCESS_SCHEMA["required"]
        assert "reason" in REQUEST_COMMAND_ACCESS_SCHEMA["required"]


# ── clarification ──────────────────────────────────────────────────────

class TestClarificationServer:
    def _make(self, cb):
        from src.agent.clarification import create_clarification_server
        return capture_tools("src.agent.clarification", create_clarification_server, cb)

    def test_server_name_is_clarification(self):
        cap = self._make(AsyncMock(return_value="answer"))
        assert cap["name"] == "clarification"

    def test_exposes_ask_user_tool(self):
        cap = self._make(AsyncMock(return_value="answer"))
        tool = get_tool(cap["tools"], "ask_user")
        assert tool.name == "ask_user"

    @pytest.mark.asyncio
    async def test_ask_user_with_choices(self):
        cb = AsyncMock(return_value="Option B")
        cap = self._make(cb)
        tool = get_tool(cap["tools"], "ask_user")

        result = await tool.handler({"question": "Which approach?", "choices": ["A", "B", "C"]})

        cb.assert_awaited_once_with("Which approach?", ["A", "B", "C"])
        assert result["content"][0]["type"] == "text"
        assert result["content"][0]["text"] == "Option B"

    @pytest.mark.asyncio
    async def test_ask_user_without_choices_passes_none(self):
        cb = AsyncMock(return_value="Yes, proceed")
        cap = self._make(cb)
        tool = get_tool(cap["tools"], "ask_user")

        result = await tool.handler({"question": "Should I continue?"})

        cb.assert_awaited_once_with("Should I continue?", None)
        assert result["content"][0]["text"] == "Yes, proceed"

    @pytest.mark.asyncio
    async def test_ask_user_missing_question_defaults_empty(self):
        cb = AsyncMock(return_value="answer")
        cap = self._make(cb)
        tool = get_tool(cap["tools"], "ask_user")

        await tool.handler({})
        cb.assert_awaited_once_with("", None)

    def test_schema_requires_question(self):
        from src.agent.clarification import ASK_USER_SCHEMA
        assert "question" in ASK_USER_SCHEMA["required"]


# ── commit_message ─────────────────────────────────────────────────────

class TestCommitMessageServer:
    def _make(self, cb):
        from src.agent.commit_message import create_commit_message_server
        return capture_tools("src.agent.commit_message", create_commit_message_server, cb)

    def test_server_name_is_commit_message(self):
        cap = self._make(AsyncMock(return_value="saved"))
        assert cap["name"] == "commit_message"

    def test_exposes_set_commit_message_tool(self):
        cap = self._make(AsyncMock(return_value="saved"))
        tool = get_tool(cap["tools"], "set_commit_message")
        assert tool.name == "set_commit_message"

    @pytest.mark.asyncio
    async def test_set_commit_message_calls_callback_and_returns_result(self):
        cb = AsyncMock(return_value="Commit message saved")
        cap = self._make(cb)
        tool = get_tool(cap["tools"], "set_commit_message")

        result = await tool.handler({"message": "Add user authentication"})

        cb.assert_awaited_once_with("Add user authentication")
        assert result["content"][0]["type"] == "text"
        assert result["content"][0]["text"] == "Commit message saved"

    @pytest.mark.asyncio
    async def test_set_commit_message_missing_message_defaults_empty(self):
        cb = AsyncMock(return_value="saved")
        cap = self._make(cb)
        tool = get_tool(cap["tools"], "set_commit_message")

        await tool.handler({})
        cb.assert_awaited_once_with("")

    def test_schema_requires_message(self):
        from src.agent.commit_message import SET_COMMIT_MESSAGE_SCHEMA
        assert "message" in SET_COMMIT_MESSAGE_SCHEMA["required"]


# ── todo ───────────────────────────────────────────────────────────────

class TestTodoServer:
    def _make(self, create_cb, delete_cb=None, epic_cb=None):
        from src.agent.todo import create_todo_server
        return capture_tools(
            "src.agent.todo", create_todo_server, create_cb, delete_cb, epic_cb
        )

    def test_server_name_is_todo(self):
        cap = self._make(AsyncMock(return_value={"id": "1", "title": "T"}))
        assert cap["name"] == "todo"

    def test_only_create_todo_when_no_optional_callbacks(self):
        cap = self._make(AsyncMock(return_value={"id": "1", "title": "T"}))
        names = [t.name for t in cap["tools"]]
        assert "create_todo" in names
        assert "delete_todo" not in names
        assert "create_epic" not in names

    def test_all_tools_present_with_all_callbacks(self):
        cap = self._make(
            AsyncMock(return_value={"id": "1", "title": "T"}),
            AsyncMock(return_value="Deleted"),
            AsyncMock(return_value={"id": "e1", "title": "Epic", "color": "blue"}),
        )
        names = [t.name for t in cap["tools"]]
        assert "create_todo" in names
        assert "delete_todo" in names
        assert "create_epic" in names

    @pytest.mark.asyncio
    async def test_create_todo_basic_calls_callback(self):
        cb = AsyncMock(return_value={"id": "42", "title": "Write tests"})
        cap = self._make(cb)
        tool = get_tool(cap["tools"], "create_todo")

        result = await tool.handler({"title": "Write tests"})

        cb.assert_awaited_once_with("Write tests", "", None, None, False)
        assert "Write tests" in result["content"][0]["text"]
        assert "42" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_create_todo_with_all_fields(self):
        cb = AsyncMock(return_value={"id": "99", "title": "Full Task"})
        cap = self._make(cb)
        tool = get_tool(cap["tools"], "create_todo")

        await tool.handler({
            "title": "Full Task",
            "description": "Do all the things",
            "epic_id": "epic-1",
            "requires": ["dep-1", "dep-2"],
            "autostart": True,
        })

        cb.assert_awaited_once_with(
            "Full Task", "Do all the things", "epic-1", ["dep-1", "dep-2"], True
        )

    @pytest.mark.asyncio
    async def test_create_todo_autostart_scheduled_message(self):
        cb = AsyncMock(return_value={
            "id": "5", "title": "Auto Task", "autostart_scheduled": True
        })
        cap = self._make(cb)
        tool = get_tool(cap["tools"], "create_todo")

        result = await tool.handler({"title": "Auto Task", "autostart": True})
        assert "auto-start scheduled" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_create_todo_autostart_with_requires_shows_dep_message(self):
        cb = AsyncMock(return_value={"id": "6", "title": "Dep Task"})
        cap = self._make(cb)
        tool = get_tool(cap["tools"], "create_todo")

        result = await tool.handler({
            "title": "Dep Task",
            "requires": ["dep-1"],
            "autostart": True,
        })
        assert "dependencies" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_create_todo_autostart_unscheduled_no_deps_message(self):
        """autostart=True, no requires, autostart_scheduled missing -> cannot schedule."""
        cb = AsyncMock(return_value={"id": "7", "title": "Task"})
        cap = self._make(cb)
        tool = get_tool(cap["tools"], "create_todo")

        result = await tool.handler({"title": "Task", "autostart": True})
        assert "could not be scheduled" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_delete_todo_calls_callback_with_item_id(self):
        create_cb = AsyncMock(return_value={"id": "1", "title": "T"})
        delete_cb = AsyncMock(return_value="Item deleted successfully")
        cap = self._make(create_cb, delete_cb)
        tool = get_tool(cap["tools"], "delete_todo")

        result = await tool.handler({"item_id": "item-123"})

        delete_cb.assert_awaited_once_with("item-123")
        assert result["content"][0]["text"] == "Item deleted successfully"

    @pytest.mark.asyncio
    async def test_delete_todo_missing_item_id_defaults_empty(self):
        create_cb = AsyncMock(return_value={"id": "1", "title": "T"})
        delete_cb = AsyncMock(return_value="deleted")
        cap = self._make(create_cb, delete_cb)
        tool = get_tool(cap["tools"], "delete_todo")

        await tool.handler({})
        delete_cb.assert_awaited_once_with("")

    @pytest.mark.asyncio
    async def test_create_epic_calls_callback(self):
        create_cb = AsyncMock(return_value={"id": "1", "title": "T"})
        epic_cb = AsyncMock(return_value={
            "id": "epic-1", "title": "Auth Feature", "color": "purple"
        })
        cap = self._make(create_cb, epic_cb=epic_cb)
        tool = get_tool(cap["tools"], "create_epic")

        result = await tool.handler({"title": "Auth Feature", "color": "purple"})

        epic_cb.assert_awaited_once_with("Auth Feature", "purple")
        text = result["content"][0]["text"]
        assert "Auth Feature" in text
        assert "epic-1" in text
        assert "purple" in text

    @pytest.mark.asyncio
    async def test_create_epic_default_color_is_blue(self):
        create_cb = AsyncMock(return_value={"id": "1", "title": "T"})
        epic_cb = AsyncMock(return_value={
            "id": "e2", "title": "Epic", "color": "blue"
        })
        cap = self._make(create_cb, epic_cb=epic_cb)
        tool = get_tool(cap["tools"], "create_epic")

        await tool.handler({"title": "Epic"})
        epic_cb.assert_awaited_once_with("Epic", "blue")

    def test_create_todo_schema_title_required(self):
        from src.agent.todo import CREATE_TODO_SCHEMA
        assert "title" in CREATE_TODO_SCHEMA["required"]

    def test_create_epic_schema_title_required(self):
        from src.agent.todo import CREATE_EPIC_SCHEMA
        assert "title" in CREATE_EPIC_SCHEMA["required"]

    def test_delete_todo_schema_item_id_required(self):
        from src.agent.todo import DELETE_TODO_SCHEMA
        assert "item_id" in DELETE_TODO_SCHEMA["required"]
