"""Unit tests for MCP tool server factory functions.

Each module exposes a create_*_server() factory that returns an MCP server dict.
We patch create_sdk_mcp_server to capture the SdkMcpTool objects, then call
.handler(input_dict) directly to verify callback invocation and return values.
"""

import importlib

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


# The create_todo tool passes title / description positionally and the rest by keyword.
_TODO_OPTION_NAMES = ("epic_id", "requires", "autostart", "auto_approve", "use_chrome")


def _assert_todo_call(cb, expected):
    """``cb`` was awaited once with (title, description, epic_id, requires, autostart, auto_approve, use_chrome)."""
    title, description, *options = expected
    cb.assert_awaited_once_with(title, description, **dict(zip(_TODO_OPTION_NAMES, options)))


def _text(result):
    """The text of the first content block of a tool result."""
    return result["content"][0]["text"]


class _SingleToolServer:
    """Shared plumbing for a server whose factory takes one callback.

    Subclasses set MODULE (``src.agent.<name>``), SERVER (server and factory
    suffix), TOOL (tool name) and CB_RETURN (a harmless callback result). Not
    collected itself (no ``Test`` prefix); its tests run once per subclass.
    """

    MODULE = ""
    SERVER = ""
    TOOL = ""
    CB_RETURN = None

    def _make(self, cb):
        module = importlib.import_module(self.MODULE)
        factory = getattr(module, f"create_{self.SERVER}_server")
        return capture_tools(self.MODULE, factory, cb)

    def _tool(self, cb=None):
        cb = cb or AsyncMock(return_value=self.CB_RETURN)
        return get_tool(self._make(cb)["tools"], self.TOOL)

    def _schema(self, name):
        return getattr(importlib.import_module(self.MODULE), name)

    async def _call(self, return_value, tool_input):
        """Invoke the tool with a callback returning return_value.

        Returns (callback, result).
        """
        cb = AsyncMock(return_value=return_value)
        result = await self._tool(cb).handler(tool_input)
        return cb, result

    def test_server_name(self):
        cap = self._make(AsyncMock(return_value=self.CB_RETURN))
        assert cap["name"] == self.SERVER

    def test_exposes_tool(self):
        assert self._tool().name == self.TOOL


# ── board_view ─────────────────────────────────────────────────────────

class TestBoardViewServer(_SingleToolServer):
    MODULE = "src.agent.board_view"
    SERVER = "board_view"
    TOOL = "view_board"
    CB_RETURN = ""

    def test_view_board_has_description(self):
        assert len(self._tool().description) > 0

    @pytest.mark.asyncio
    async def test_view_board_calls_callback_no_args(self):
        cb, result = await self._call("## Board\n- Todo: Fix bug", {})

        cb.assert_awaited_once_with()
        assert result["content"][0]["type"] == "text"
        assert _text(result) == "## Board\n- Todo: Fix bug"

    @pytest.mark.asyncio
    async def test_view_board_returns_callback_text(self):
        _cb, result = await self._call("Empty board", {})
        assert _text(result) == "Empty board"

    def test_view_board_schema(self):
        schema = self._schema("VIEW_BOARD_SCHEMA")
        assert schema["type"] == "object"
        assert schema["properties"] == {}


# ── who_am_i ───────────────────────────────────────────────────────────

class TestWhoAmIServer(_SingleToolServer):
    MODULE = "src.agent.who_am_i"
    SERVER = "who_am_i"
    TOOL = "who_am_i"
    CB_RETURN = {}

    def test_who_am_i_has_description(self):
        assert len(self._tool().description) > 0

    @pytest.mark.asyncio
    async def test_who_am_i_calls_callback_no_args(self):
        cb, result = await self._call(
            {"id": "abc123", "title": "Plan", "column_name": "doing"}, {}
        )

        cb.assert_awaited_once_with()
        assert result["content"][0]["type"] == "text"

    @pytest.mark.asyncio
    async def test_who_am_i_includes_item_id_and_deps(self):
        _cb, result = await self._call({
            "id": "abc123",
            "title": "Build foundation",
            "column_name": "doing",
            "dependencies": [{"id": "dep-1"}, {"id": "dep-2"}],
        }, {})

        text = _text(result)
        assert "abc123" in text
        assert "Build foundation" in text
        assert "dep-1" in text and "dep-2" in text

    @pytest.mark.asyncio
    async def test_who_am_i_handles_error(self):
        _cb, result = await self._call({"error": "Board item xyz not found."}, {})
        assert "not found" in _text(result)

    def test_who_am_i_schema(self):
        schema = self._schema("WHO_AM_I_SCHEMA")
        assert schema["type"] == "object"
        assert schema["properties"] == {}


# ── shortcut ───────────────────────────────────────────────────────────

class TestShortcutServer(_SingleToolServer):
    MODULE = "src.agent.shortcut"
    SERVER = "shortcut"
    TOOL = "create_shortcut"
    CB_RETURN = {"name": "x"}

    @pytest.mark.asyncio
    async def test_create_shortcut_passes_name_and_command(self):
        cb, result = await self._call(
            {"name": "Run tests"}, {"name": "Run tests", "command": "pytest"}
        )

        cb.assert_awaited_once_with("Run tests", "pytest")
        assert result["content"][0]["type"] == "text"
        assert "Run tests" in _text(result)

    @pytest.mark.asyncio
    async def test_create_shortcut_uses_callback_name_in_response(self):
        _cb, result = await self._call(
            {"name": "Normalized Name"}, {"name": "raw name", "command": "npm test"}
        )
        assert "Normalized Name" in _text(result)

    @pytest.mark.asyncio
    async def test_create_shortcut_missing_fields_default_empty(self):
        cb, _result = await self._call({"name": ""}, {})
        cb.assert_awaited_once_with("", "")

    def test_schema_requires_name_and_command(self):
        schema = self._schema("CREATE_SHORTCUT_SCHEMA")
        assert "name" in schema["required"]
        assert "command" in schema["required"]


# ── tool_access / command_access ───────────────────────────────────────

class _AccessRequestServer(_SingleToolServer):
    """request_*_access servers: callback(<FIELD>, reason) -> "approved"/"denied".

    Subclasses also set FIELD (the first input key), SCHEMA (schema constant
    name) and APPROVED_INPUT / DENIED_INPUT as (FIELD value, reason) pairs.
    """

    CB_RETURN = "approved"
    FIELD = ""
    SCHEMA = ""
    APPROVED_INPUT = ("", "")
    DENIED_INPUT = ("", "")

    def _input(self, pair):
        value, reason = pair
        return {self.FIELD: value, "reason": reason}

    @pytest.mark.asyncio
    async def test_approved_response(self):
        cb, result = await self._call("approved", self._input(self.APPROVED_INPUT))

        cb.assert_awaited_once_with(*self.APPROVED_INPUT)
        assert _text(result) == "approved"

    @pytest.mark.asyncio
    async def test_denied_response(self):
        _cb, result = await self._call("denied", self._input(self.DENIED_INPUT))
        assert _text(result) == "denied"

    @pytest.mark.asyncio
    async def test_missing_fields_default_empty(self):
        cb, _result = await self._call("denied", {})
        cb.assert_awaited_once_with("", "")

    def test_schema_required_fields(self):
        schema = self._schema(self.SCHEMA)
        assert self.FIELD in schema["required"]
        assert "reason" in schema["required"]


class TestToolAccessServer(_AccessRequestServer):
    MODULE = "src.agent.tool_access"
    SERVER = "tool_access"
    TOOL = "request_tool_access"
    FIELD = "tool_name"
    SCHEMA = "REQUEST_TOOL_ACCESS_SCHEMA"
    APPROVED_INPUT = ("WebSearch", "Need to search docs")
    DENIED_INPUT = ("WebFetch", "Fetch a URL")


class TestCommandAccessServer(_AccessRequestServer):
    MODULE = "src.agent.command_access"
    SERVER = "command_access"
    TOOL = "request_command_access"
    FIELD = "command"
    SCHEMA = "REQUEST_COMMAND_ACCESS_SCHEMA"
    APPROVED_INPUT = ("flutter", "Build mobile app")
    DENIED_INPUT = ("rm", "Clean files")


# ── clarification ──────────────────────────────────────────────────────

class TestClarificationServer(_SingleToolServer):
    MODULE = "src.agent.clarification"
    SERVER = "clarification"
    TOOL = "ask_user"
    CB_RETURN = "answer"

    @pytest.mark.asyncio
    async def test_ask_user_with_choices(self):
        cb, result = await self._call(
            "Option B", {"question": "Which approach?", "choices": ["A", "B", "C"]}
        )

        cb.assert_awaited_once_with("Which approach?", ["A", "B", "C"], None)
        assert result["content"][0]["type"] == "text"
        assert _text(result) == "Option B"

    @pytest.mark.asyncio
    async def test_ask_user_without_choices_passes_none(self):
        cb, result = await self._call("Yes, proceed", {"question": "Should I continue?"})

        cb.assert_awaited_once_with("Should I continue?", None, None)
        assert _text(result) == "Yes, proceed"

    @pytest.mark.asyncio
    async def test_ask_user_missing_question_defaults_empty(self):
        cb, _result = await self._call("answer", {})
        cb.assert_awaited_once_with("", None, None)

    @pytest.mark.asyncio
    async def test_ask_user_passes_context(self):
        cb, _result = await self._call("Approved", {
            "question": "Approve plan?",
            "choices": ["Yes", "No"],
            "context": "Considered options A and B; chose A.",
        })

        cb.assert_awaited_once_with(
            "Approve plan?", ["Yes", "No"], "Considered options A and B; chose A."
        )

    def test_schema_includes_context(self):
        schema = self._schema("ASK_USER_SCHEMA")
        assert "context" in schema["properties"]
        assert schema["properties"]["context"]["type"] == "string"
        # context is optional
        assert "context" not in schema.get("required", [])

    def test_schema_requires_question(self):
        assert "question" in self._schema("ASK_USER_SCHEMA")["required"]


# ── commit_message ─────────────────────────────────────────────────────

class TestCommitMessageServer(_SingleToolServer):
    MODULE = "src.agent.commit_message"
    SERVER = "commit_message"
    TOOL = "set_commit_message"
    CB_RETURN = "saved"

    @pytest.mark.asyncio
    async def test_set_commit_message_calls_callback_and_returns_result(self):
        cb, result = await self._call(
            "Commit message saved", {"message": "Add user authentication"}
        )

        cb.assert_awaited_once_with("Add user authentication")
        assert result["content"][0]["type"] == "text"
        assert _text(result) == "Commit message saved"

    @pytest.mark.asyncio
    async def test_set_commit_message_missing_message_defaults_empty(self):
        cb, _result = await self._call("saved", {})
        cb.assert_awaited_once_with("")

    def test_schema_requires_message(self):
        assert "message" in self._schema("SET_COMMIT_MESSAGE_SCHEMA")["required"]


# ── todo ───────────────────────────────────────────────────────────────

_TODO = {"id": "1", "title": "T"}


class TestTodoServer:
    # Position of each tool's callback in create_todo_server(create, delete, epic).
    _CALLBACK_SLOT = {"create_todo": 0, "delete_todo": 1, "create_epic": 2}

    def _make(self, create_cb, delete_cb=None, epic_cb=None):
        from src.agent.todo import create_todo_server
        return capture_tools(
            "src.agent.todo", create_todo_server, create_cb, delete_cb, epic_cb
        )

    async def _call(self, tool_name, return_value, tool_input):
        """Invoke tool_name with its callback returning return_value.

        create_todo always gets a callback (it is required); the other
        optional callback stays None. Returns (callback, result).
        """
        callbacks = [AsyncMock(return_value=_TODO), None, None]
        cb = AsyncMock(return_value=return_value)
        callbacks[self._CALLBACK_SLOT[tool_name]] = cb
        tool = get_tool(self._make(*callbacks)["tools"], tool_name)
        return cb, await tool.handler(tool_input)

    def test_server_name_is_todo(self):
        cap = self._make(AsyncMock(return_value=_TODO))
        assert cap["name"] == "todo"

    def test_only_create_todo_when_no_optional_callbacks(self):
        cap = self._make(AsyncMock(return_value=_TODO))
        names = [t.name for t in cap["tools"]]
        assert "create_todo" in names
        assert "delete_todo" not in names
        assert "create_epic" not in names

    def test_all_tools_present_with_all_callbacks(self):
        cap = self._make(
            AsyncMock(return_value=_TODO),
            AsyncMock(return_value="Deleted"),
            AsyncMock(return_value={"id": "e1", "title": "Epic", "color": "blue"}),
        )
        names = [t.name for t in cap["tools"]]
        assert "create_todo" in names
        assert "delete_todo" in names
        assert "create_epic" in names

    # Each case: callback return, tool input, expected callback args
    # (title, description, epic_id, requires, autostart, auto_approve,
    # use_chrome), substrings expected in the result text.
    @pytest.mark.asyncio
    @pytest.mark.parametrize("cb_return, tool_input, expected_args, expected_text", [
        pytest.param(
            {"id": "42", "title": "Write tests"}, {"title": "Write tests"},
            ("Write tests", "", None, None, False, 0, False), ["Write tests", "42"],
            id="basic_calls_callback",
        ),
        # auto_approve=1 should be forwarded and surfaced in the result message.
        pytest.param(
            {"id": "10", "title": "Reviewed Task"},
            {"title": "Reviewed Task", "auto_approve": 1},
            ("Reviewed Task", "", None, None, False, 1, False), ["review mode"],
            id="auto_approve_review_message",
        ),
        # auto_approve=2 should be forwarded and surfaced as direct merge.
        pytest.param(
            {"id": "11", "title": "Direct Task"},
            {"title": "Direct Task", "auto_approve": 2},
            ("Direct Task", "", None, None, False, 2, False), ["direct merge"],
            id="auto_approve_direct_message",
        ),
        # Both autostart and auto_approve can be set on the same call.
        pytest.param(
            {"id": "13", "title": "Both", "autostart_scheduled": True},
            {"title": "Both", "autostart": True, "auto_approve": 1},
            ("Both", "", None, None, True, 1, False),
            ["auto-start scheduled", "review mode"],
            id="autostart_and_auto_approve_together",
        ),
    ])
    async def test_create_todo_forwards_args_and_reports(
        self, cb_return, tool_input, expected_args, expected_text
    ):
        cb, result = await self._call("create_todo", cb_return, tool_input)

        _assert_todo_call(cb, expected_args)
        text = _text(result)
        for fragment in expected_text:
            assert fragment in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_input, expected_args", [
        pytest.param(
            {
                "title": "Full Task",
                "description": "Do all the things",
                "epic_id": "epic-1",
                "requires": ["dep-1", "dep-2"],
                "autostart": True,
                "auto_approve": 2,
                "use_chrome": True,
            },
            ("Full Task", "Do all the things", "epic-1", ["dep-1", "dep-2"], True, 2, True),
            id="with_all_fields",
        ),
        # Out-of-range auto_approve values must be coerced to 0 (OFF).
        pytest.param(
            {"title": "T", "auto_approve": 7},
            ("T", "", None, None, False, 0, False),
            id="auto_approve_invalid_falls_back_to_off",
        ),
    ])
    async def test_create_todo_forwards_args(self, tool_input, expected_args):
        cb, _result = await self._call("create_todo", _TODO, tool_input)
        _assert_todo_call(cb, expected_args)

    @pytest.mark.asyncio
    async def test_create_todo_use_chrome_defaults_false(self):
        cb, _result = await self._call(
            "create_todo", {"id": "7", "title": "Code Task"}, {"title": "Code Task"}
        )

        # use_chrome is passed explicitly and defaults to False.
        assert cb.await_args.kwargs["use_chrome"] is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cb_return, tool_input, expected_fragment", [
        pytest.param(
            {"id": "8", "title": "Browse Task"},
            {"title": "Browse Task", "use_chrome": True},
            "browser access enabled",
            id="use_chrome_message",
        ),
        pytest.param(
            {"id": "5", "title": "Auto Task", "autostart_scheduled": True},
            {"title": "Auto Task", "autostart": True},
            "auto-start scheduled",
            id="autostart_scheduled_message",
        ),
        pytest.param(
            {"id": "6", "title": "Dep Task"},
            {"title": "Dep Task", "requires": ["dep-1"], "autostart": True},
            "dependencies",
            id="autostart_with_requires_shows_dep_message",
        ),
        # autostart=True, no requires, autostart_scheduled missing -> cannot schedule.
        pytest.param(
            {"id": "7", "title": "Task"},
            {"title": "Task", "autostart": True},
            "could not be scheduled",
            id="autostart_unscheduled_no_deps_message",
        ),
    ])
    async def test_create_todo_result_message(self, cb_return, tool_input, expected_fragment):
        _cb, result = await self._call("create_todo", cb_return, tool_input)
        assert expected_fragment in _text(result)

    def test_create_todo_schema_has_use_chrome(self):
        from src.agent.todo import CREATE_TODO_SCHEMA
        assert "use_chrome" in CREATE_TODO_SCHEMA["properties"]
        assert CREATE_TODO_SCHEMA["properties"]["use_chrome"]["type"] == "boolean"

    @pytest.mark.asyncio
    async def test_delete_todo_calls_callback_with_item_id(self):
        cb, result = await self._call(
            "delete_todo", "Item deleted successfully", {"item_id": "item-123"}
        )

        cb.assert_awaited_once_with("item-123")
        assert _text(result) == "Item deleted successfully"

    @pytest.mark.asyncio
    async def test_delete_todo_missing_item_id_defaults_empty(self):
        cb, _result = await self._call("delete_todo", "deleted", {})
        cb.assert_awaited_once_with("")

    @pytest.mark.asyncio
    async def test_create_epic_calls_callback(self):
        cb, result = await self._call(
            "create_epic",
            {"id": "epic-1", "title": "Auth Feature", "color": "purple"},
            {"title": "Auth Feature", "color": "purple"},
        )

        cb.assert_awaited_once_with("Auth Feature", "purple")
        text = _text(result)
        assert "Auth Feature" in text
        assert "epic-1" in text
        assert "purple" in text

    @pytest.mark.asyncio
    async def test_create_epic_default_color_is_blue(self):
        cb, _result = await self._call(
            "create_epic", {"id": "e2", "title": "Epic", "color": "blue"}, {"title": "Epic"}
        )
        cb.assert_awaited_once_with("Epic", "blue")

    def test_create_todo_schema_title_required(self):
        from src.agent.todo import CREATE_TODO_SCHEMA
        assert "title" in CREATE_TODO_SCHEMA["required"]

    def test_create_todo_schema_has_auto_approve(self):
        """Schema should expose auto_approve as an integer enum [0, 1, 2]."""
        from src.agent.todo import CREATE_TODO_SCHEMA
        prop = CREATE_TODO_SCHEMA["properties"].get("auto_approve")
        assert prop is not None, "create_todo schema must expose auto_approve"
        assert prop["type"] == "integer"
        assert prop["enum"] == [0, 1, 2]

    def test_create_epic_schema_title_required(self):
        from src.agent.todo import CREATE_EPIC_SCHEMA
        assert "title" in CREATE_EPIC_SCHEMA["required"]

    def test_delete_todo_schema_item_id_required(self):
        from src.agent.todo import DELETE_TODO_SCHEMA
        assert "item_id" in DELETE_TODO_SCHEMA["required"]
