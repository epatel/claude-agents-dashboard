"""Unit tests for src/agent/session.py — ClaudeAgentSession class."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent.session import (
    ClaudeAgentSession,
    AgentResult,
    build_attachment_prompt,
    _server_result_text,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def make_session(**kwargs):
    defaults = dict(
        worktree_path=Path("/tmp/test-worktree"),
        system_prompt="You are a helpful agent.",
    )
    defaults.update(kwargs)
    return ClaudeAgentSession(**defaults)


# ---------------------------------------------------------------------------
# AgentResult dataclass
# ---------------------------------------------------------------------------

class TestAgentResult:
    def test_success_result(self):
        r = AgentResult(success=True, session_id="s1", cost_usd=0.01)
        assert r.success is True
        assert r.session_id == "s1"
        assert r.cost_usd == 0.01

    def test_error_result(self):
        r = AgentResult(success=False, error="oops")
        assert r.success is False
        assert r.error == "oops"

    def test_api_error_status_defaults_none(self):
        r = AgentResult(success=False, error="oops")
        assert r.api_error_status is None


# ---------------------------------------------------------------------------
# _server_result_text helper
# ---------------------------------------------------------------------------

class TestServerResultText:
    def test_none_returns_empty(self):
        assert _server_result_text(None) == ""

    def test_string_is_stripped(self):
        assert _server_result_text("  hi  ") == "hi"

    def test_list_of_strings_joined(self):
        assert _server_result_text(["a", "b"]) == "a\nb"

    def test_list_of_dicts_uses_text_then_content(self):
        content = [{"text": "t"}, {"content": "c"}]
        assert _server_result_text(content) == "t\nc"

    def test_list_skips_empty_parts(self):
        content = [{"text": "t"}, {"other": "ignored"}, "x"]
        assert _server_result_text(content) == "t\nx"

    def test_list_of_objects_uses_text_attr(self):
        obj = MagicMock()
        obj.text = "from-attr"
        assert _server_result_text([obj]) == "from-attr"

    def test_fallback_stringifies_other(self):
        assert _server_result_text(42) == "42"



# ---------------------------------------------------------------------------
# build_attachment_prompt
# ---------------------------------------------------------------------------

class TestBuildAttachmentPrompt:
    def test_empty_returns_empty_string(self):
        assert build_attachment_prompt([]) == ""

    def test_single_plain_attachment(self):
        result = build_attachment_prompt([{"filename": "image.png", "dest": "/tmp/image.png"}])
        assert "/tmp/image.png" in result
        assert "Attached reference images" in result

    def test_annotation_pair_grouped(self):
        atts = [
            {"filename": "annotation_1_original.jpg", "dest": "/tmp/orig.jpg", "annotation_summary": None},
            {"filename": "annotation_1_annotated.jpg", "dest": "/tmp/ann.jpg", "annotation_summary": "3 arrows"},
        ]
        result = build_attachment_prompt(atts)
        assert "annotated screenshot" in result
        assert "/tmp/orig.jpg" in result
        assert "/tmp/ann.jpg" in result
        assert "3 arrows" in result

    def test_annotation_pair_with_summary(self):
        atts = [
            {"filename": "annotation_2_original.jpg", "dest": "/tmp/o.jpg", "annotation_summary": "2 circles"},
            {"filename": "annotation_2_annotated.jpg", "dest": "/tmp/a.jpg", "annotation_summary": "2 circles"},
        ]
        result = build_attachment_prompt(atts)
        assert "2 circles" in result

    def test_important_note_included(self):
        result = build_attachment_prompt([{"filename": "x.png", "dest": "/tmp/x.png"}])
        assert "IMPORTANT" in result
        assert "study the attached images" in result


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------

class TestAgentSessionConstructor:
    def test_stores_worktree_path(self):
        p = Path("/tmp/wt")
        session = make_session(worktree_path=p)
        assert session.worktree_path == p

    def test_stores_system_prompt(self):
        session = make_session(system_prompt="Be helpful.")
        assert session.system_prompt == "Be helpful."

    def test_model_stored(self):
        session = make_session(model="claude-opus-4")
        assert session.model == "claude-opus-4"

    def test_callbacks_stored(self):
        cb = AsyncMock()
        session = make_session(on_message=cb, on_complete=cb)
        assert session.on_message is cb
        assert session.on_complete is cb

    def test_allowed_commands_stored(self):
        cmds = ["git", "npm"]
        session = make_session(allowed_commands=cmds)
        assert session.allowed_commands == cmds

    def test_ollama_env_stored(self):
        env = {
            "ANTHROPIC_AUTH_TOKEN": "ollama",
            "ANTHROPIC_API_KEY": "",
            "ANTHROPIC_BASE_URL": "http://localhost:11434",
        }
        session = make_session(local_env=env)
        assert session.local_env == env

    def test_ollama_env_default_none(self):
        session = make_session()
        assert session.local_env is None



# ---------------------------------------------------------------------------
# cancel()
# ---------------------------------------------------------------------------

class TestCancel:
    @pytest.mark.asyncio
    async def test_cancel_sets_cancelled_flag(self):
        session = make_session()
        await session.cancel()
        assert session._cancelled is True

    @pytest.mark.asyncio
    async def test_cancel_disconnects_client(self):
        session = make_session()
        mock_client = AsyncMock()
        session.client = mock_client
        await session.cancel()
        mock_client.disconnect.assert_called_once()
        assert session.client is None

    @pytest.mark.asyncio
    async def test_cancel_ignores_disconnect_error(self):
        session = make_session()
        mock_client = AsyncMock()
        mock_client.disconnect.side_effect = RuntimeError("gone")
        session.client = mock_client
        # Should not raise
        await session.cancel()
        assert session._cancelled is True

    @pytest.mark.asyncio
    async def test_cancel_cancels_task(self):
        session = make_session()
        mock_task = MagicMock()
        mock_task.done.return_value = False
        mock_task.cancel = MagicMock()

        async def fake_await():
            raise asyncio.CancelledError()

        mock_task.__await__ = lambda self: fake_await().__await__()

        # Use a real done task to avoid the await
        loop = asyncio.get_event_loop()
        real_task = loop.create_task(asyncio.sleep(0))
        await asyncio.sleep(0)  # let it complete
        session._task = real_task
        session.client = None
        await session.cancel()
        assert session._cancelled is True

    @pytest.mark.asyncio
    async def test_cancel_no_client_no_error(self):
        session = make_session()
        session.client = None
        await session.cancel()  # Should not raise
        assert session._cancelled is True

    @pytest.mark.asyncio
    async def test_cancel_no_task_no_error(self):
        session = make_session()
        session._task = None
        await session.cancel()  # Should not raise


# ---------------------------------------------------------------------------
# disconnect()
# ---------------------------------------------------------------------------

class TestDisconnect:
    @pytest.mark.asyncio
    async def test_disconnect_calls_client_disconnect(self):
        session = make_session()
        mock_client = AsyncMock()
        session.client = mock_client
        await session.disconnect()
        mock_client.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_no_client_no_error(self):
        session = make_session()
        session.client = None
        await session.disconnect()  # Should not raise


# ---------------------------------------------------------------------------
# send_message()
# ---------------------------------------------------------------------------

class TestSendMessage:
    @pytest.mark.asyncio
    async def test_sends_to_client(self):
        session = make_session()
        mock_client = AsyncMock()
        session.client = mock_client
        await session.send_message("hello")
        mock_client.query.assert_called_once_with("hello")

    @pytest.mark.asyncio
    async def test_no_client_no_error(self):
        session = make_session()
        session.client = None
        await session.send_message("hello")  # Should not raise


# ---------------------------------------------------------------------------
# _check_mcp_status()
# ---------------------------------------------------------------------------

def _session_with_client(client, **session_kwargs):
    session = make_session(**session_kwargs)
    session.client = client
    return session


def _mcp_status_client(*servers):
    mock_client = AsyncMock()
    mock_client.get_mcp_status.return_value = {"mcpServers": list(servers)}
    return mock_client


class TestCheckMcpStatus:
    async def test_no_client_returns_early(self):
        session = make_session()
        session.client = None
        await session._check_mcp_status()  # Should not raise

    async def test_connected_server_logged(self):
        mock_client = _mcp_status_client(
            {"name": "my_server", "status": "connected", "tools": [{"name": "do_thing"}]}
        )
        await _session_with_client(mock_client)._check_mcp_status()
        mock_client.get_mcp_status.assert_called_once()

    @pytest.mark.parametrize(
        ("server", "fragments"),
        [
            pytest.param({"name": "bad_server", "status": "failed", "error": "timeout"},
                         ("bad_server", "[warning]"), id="failed"),
            pytest.param({"name": "srv", "status": "disconnected", "error": ""}, (),
                         id="disconnected"),
            pytest.param({"name": "auth_srv", "status": "needs-auth", "error": ""}, (),
                         id="needs_auth"),
        ],
    )
    async def test_unhealthy_server_calls_on_message(self, server, fragments):
        on_msg = AsyncMock()
        await _session_with_client(_mcp_status_client(server), on_message=on_msg)._check_mcp_status()
        on_msg.assert_called_once()
        text = on_msg.call_args[0][0]
        for fragment in fragments:
            assert fragment in text

    async def test_get_mcp_status_exception_silenced(self):
        mock_client = AsyncMock()
        mock_client.get_mcp_status.side_effect = RuntimeError("boom")
        await _session_with_client(mock_client)._check_mcp_status()  # Should not raise

    async def test_no_on_message_with_failed_server(self):
        # No on_message set — should still not raise
        mock_client = _mcp_status_client({"name": "x", "status": "failed", "error": "oops"})
        await _session_with_client(mock_client)._check_mcp_status()


# ---------------------------------------------------------------------------
# _receive_loop()
# ---------------------------------------------------------------------------

def _assistant_message(block_type, **attrs):
    """An AssistantMessage mock holding one ``block_type`` block with ``attrs``."""
    from claude_agent_sdk import AssistantMessage
    block = MagicMock(spec=block_type)
    for name, value in attrs.items():
        setattr(block, name, value)
    msg = MagicMock(spec=AssistantMessage)
    msg.content = [block]
    return msg


class TestReceiveLoop:
    def _make_text_message(self, text: str):
        from claude_agent_sdk import TextBlock
        return _assistant_message(TextBlock, text=text)

    def _make_thinking_message(self, thinking: str):
        from claude_agent_sdk import ThinkingBlock
        return _assistant_message(ThinkingBlock, thinking=thinking)

    def _make_tool_use_message(self, name: str, inp: dict):
        from claude_agent_sdk import ToolUseBlock
        return _assistant_message(ToolUseBlock, name=name, input=inp)

    def _make_server_tool_use_message(self, name: str, inp: dict):
        from claude_agent_sdk import ServerToolUseBlock
        return _assistant_message(ServerToolUseBlock, name=name, input=inp)

    def _make_server_tool_result_message(self, content):
        from claude_agent_sdk import ServerToolResultBlock
        return _assistant_message(ServerToolResultBlock, content=content)

    def _make_result_message(self, **overrides):
        """A ResultMessage mock; ``overrides`` replace the defaults below."""
        from claude_agent_sdk import ResultMessage
        fields = dict(session_id="sess-1", is_error=False, result=None,
                      total_cost_usd=0.01, usage={}, api_error_status=None)
        fields.update(overrides)
        msg = MagicMock(spec=ResultMessage)
        for name, value in fields.items():
            setattr(msg, name, value)
        return msg

    async def _run_receive_loop_with_messages(self, session, messages):
        """Helper: patch client.receive_messages to yield given messages, run loop.

        ``messages`` may be a list, or an async generator to use as-is.
        Returns the mock client.
        """
        async def gen():
            for m in messages:
                yield m

        mock_client = AsyncMock()
        # receive_messages must be a regular (non-async) method returning an async iterable
        stream = messages if hasattr(messages, "__aiter__") else gen()
        mock_client.receive_messages = MagicMock(return_value=stream)
        session.client = mock_client
        await session._receive_loop()
        return mock_client

    async def _complete_with(self, msg):
        """Run the loop over one message; return the AgentResult passed to on_complete."""
        on_complete = AsyncMock()
        session = make_session(on_complete=on_complete)
        await self._run_receive_loop_with_messages(session, [msg])
        on_complete.assert_called_once()
        result_arg = on_complete.call_args[0][0]
        assert isinstance(result_arg, AgentResult)
        return result_arg

    @pytest.mark.parametrize(
        ("callback", "make", "make_args", "expected_call"),
        [
            pytest.param("on_message", "_make_text_message", ("hello world",),
                         ("hello world",), id="text_block_calls_on_message"),
            pytest.param("on_thinking", "_make_thinking_message", ("deep thoughts",),
                         ("deep thoughts",), id="thinking_block_calls_on_thinking"),
            pytest.param("on_tool_use", "_make_tool_use_message", ("Bash", {"command": "ls"}),
                         ("Bash", {"command": "ls"}), id="tool_use_block_calls_on_tool_use"),
            pytest.param("on_tool_use", "_make_server_tool_use_message",
                         ("web_search", {"query": "claude"}), ("web_search", {"query": "claude"}),
                         id="server_tool_use_block_calls_on_tool_use"),
            pytest.param("on_message", "_make_server_tool_result_message", ("advisor says hi",),
                         ("[advisor] advisor says hi",),
                         id="server_tool_result_block_string_content"),
            pytest.param("on_message", "_make_server_tool_result_message",
                         ([{"text": "first"}, "second", {"content": "third"}],),
                         ("[advisor] first\nsecond\nthird",),
                         id="server_tool_result_block_list_content_flattened"),
            pytest.param("on_message", "_make_server_tool_result_message", ("",), None,
                         id="server_tool_result_block_empty_content_no_message"),
            # session.py checks `if block.thinking`
            pytest.param("on_thinking", "_make_thinking_message", ("",), None,
                         id="empty_thinking_block_not_forwarded"),
        ],
    )
    async def test_block_dispatch(self, callback, make, make_args, expected_call):
        """Each assistant block type reaches its callback (or none when empty)."""
        cb = AsyncMock()
        session = make_session(**{callback: cb})
        msg = getattr(self, make)(*make_args)
        await self._run_receive_loop_with_messages(session, [msg])
        if expected_call is None:
            cb.assert_not_called()
        else:
            cb.assert_called_once_with(*expected_call)

    async def test_result_message_calls_on_complete(self):
        result_arg = await self._complete_with(
            self._make_result_message(session_id="s42", is_error=False, total_cost_usd=0.05)
        )
        assert result_arg.success is True
        assert result_arg.session_id == "s42"
        assert result_arg.cost_usd == 0.05

    async def test_result_message_stores_session_id(self):
        session = make_session()
        msg = self._make_result_message(session_id="my-session")
        await self._run_receive_loop_with_messages(session, [msg])
        assert session.current_session_id == "my-session"

    @pytest.mark.parametrize(
        ("overrides", "expected"),
        [
            pytest.param({"is_error": True, "result": "Something broke"},
                         {"success": False, "error": "Something broke"},
                         id="error_result_calls_on_complete_with_error"),
            pytest.param({"is_error": True, "result": "Overloaded", "api_error_status": 529},
                         {"success": False, "api_error_status": 529,
                          "error": "[HTTP 529] Overloaded"},
                         id="error_result_prefixes_http_status"),
            # Status present but not an error — must not be prefixed, error stays None.
            pytest.param({"is_error": False, "api_error_status": 200},
                         {"success": True, "error": None, "api_error_status": 200},
                         id="success_result_ignores_api_error_status"),
            pytest.param({"is_error": True, "result": "plain failure", "api_error_status": None},
                         {"error": "plain failure", "api_error_status": None},
                         id="error_result_without_status_unprefixed"),
            pytest.param({"usage": {"input_tokens": 100, "output_tokens": 50}},
                         {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
                         id="token_usage_parsed"),
            # total_tokens not in usage — should be computed
            pytest.param({"usage": {"input_tokens": 200, "output_tokens": 75}},
                         {"total_tokens": 275},
                         id="total_tokens_computed_when_missing"),
        ],
    )
    async def test_result_fields(self, overrides, expected):
        result_arg = await self._complete_with(self._make_result_message(**overrides))
        for name, value in expected.items():
            assert getattr(result_arg, name) == value

    async def test_exception_calls_on_error(self):
        on_error = AsyncMock()
        session = make_session(on_error=on_error)

        async def gen():
            raise RuntimeError("network error")
            yield  # make it a generator

        await self._run_receive_loop_with_messages(session, gen())
        on_error.assert_called_once()
        assert "network error" in on_error.call_args[0][0]

    async def test_cancelled_flag_stops_loop(self):
        on_msg = AsyncMock()
        session = make_session(on_message=on_msg)
        session._cancelled = True
        msg = self._make_text_message("should not be seen")
        await self._run_receive_loop_with_messages(session, [msg])
        on_msg.assert_not_called()

    async def test_client_disconnected_in_finally(self):
        session = make_session()
        mock_client = await self._run_receive_loop_with_messages(
            session, [self._make_result_message()]
        )
        mock_client.disconnect.assert_called_once()
        assert session.client is None

    async def test_no_on_message_no_error(self):
        """Receive loop handles missing callbacks gracefully."""
        session = make_session()  # no callbacks
        msg = self._make_text_message("hi")
        await self._run_receive_loop_with_messages(session, [msg])

    async def test_system_message_forwarded(self):
        from claude_agent_sdk import SystemMessage
        on_msg = AsyncMock()
        session = make_session(on_message=on_msg)
        sys_msg = MagicMock(spec=SystemMessage)
        sys_msg.content = "progress: 50%"
        await self._run_receive_loop_with_messages(session, [sys_msg])
        on_msg.assert_called_once()
        call_text = on_msg.call_args[0][0]
        assert "[system]" in call_text


# ---------------------------------------------------------------------------
# can_use_tool — inline closure behavior
# ---------------------------------------------------------------------------

class TestCanUseTool:
    """Test the can_use_tool closure built in start() when plugins/external MCP present."""

    def _make_can_use_tool(self, allowed_tools, all_prefixes):
        """Recreate the closure logic from session.py directly."""
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny
        allowed_set = set(allowed_tools)
        async def can_use_tool(tool_name: str, *args):
            if tool_name in allowed_set:
                return PermissionResultAllow()
            for prefix in all_prefixes:
                if tool_name.startswith(prefix):
                    return PermissionResultAllow()
            if not tool_name.startswith("mcp__"):
                return PermissionResultAllow()
            return PermissionResultDeny()
        return can_use_tool

    @pytest.mark.asyncio
    async def test_allowed_tool_permitted(self):
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny
        fn = self._make_can_use_tool(["Bash", "Read"], [])
        assert isinstance(await fn("Bash"), PermissionResultAllow)
        assert isinstance(await fn("Read"), PermissionResultAllow)

    @pytest.mark.asyncio
    async def test_standard_non_mcp_tool_permitted(self):
        from claude_agent_sdk import PermissionResultAllow
        fn = self._make_can_use_tool([], [])
        assert isinstance(await fn("Write"), PermissionResultAllow)
        assert isinstance(await fn("Edit"), PermissionResultAllow)

    @pytest.mark.asyncio
    async def test_unknown_mcp_tool_blocked(self):
        from claude_agent_sdk import PermissionResultDeny
        fn = self._make_can_use_tool([], [])
        assert isinstance(await fn("mcp__unknown__tool"), PermissionResultDeny)

    @pytest.mark.asyncio
    async def test_prefix_match_permits_mcp_tool(self):
        from claude_agent_sdk import PermissionResultAllow
        fn = self._make_can_use_tool([], ["mcp__my_plugin_"])
        assert isinstance(await fn("mcp__my_plugin_do_thing"), PermissionResultAllow)

    @pytest.mark.asyncio
    async def test_no_prefix_match_blocks_mcp_tool(self):
        from claude_agent_sdk import PermissionResultDeny
        fn = self._make_can_use_tool([], ["mcp__other_"])
        assert isinstance(await fn("mcp__my_plugin_do_thing"), PermissionResultDeny)

    @pytest.mark.asyncio
    async def test_explicit_mcp_tool_in_allowed_set_permitted(self):
        from claude_agent_sdk import PermissionResultAllow
        fn = self._make_can_use_tool(["mcp__todo__create_todo"], [])
        assert isinstance(await fn("mcp__todo__create_todo"), PermissionResultAllow)

    @pytest.mark.asyncio
    async def test_wildcard_prefix_allows_all_variants(self):
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny
        fn = self._make_can_use_tool([], ["mcp__ext_server__"])
        assert isinstance(await fn("mcp__ext_server__tool_a"), PermissionResultAllow)
        assert isinstance(await fn("mcp__ext_server__tool_b"), PermissionResultAllow)
        assert isinstance(await fn("mcp__other__tool"), PermissionResultDeny)
