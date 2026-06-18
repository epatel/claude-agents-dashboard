"""Unit tests for src/agent/session.py — AgentSession class."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from src.agent.session import (
    AgentSession,
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
    return AgentSession(**defaults)


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
        session = make_session(ollama_env=env)
        assert session.ollama_env == env

    def test_ollama_env_default_none(self):
        session = make_session()
        assert session.ollama_env is None



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

class TestCheckMcpStatus:
    @pytest.mark.asyncio
    async def test_no_client_returns_early(self):
        session = make_session()
        session.client = None
        await session._check_mcp_status()  # Should not raise

    @pytest.mark.asyncio
    async def test_connected_server_logged(self):
        session = make_session()
        mock_client = AsyncMock()
        mock_client.get_mcp_status.return_value = {
            "mcpServers": [
                {"name": "my_server", "status": "connected", "tools": [{"name": "do_thing"}]}
            ]
        }
        session.client = mock_client
        await session._check_mcp_status()
        mock_client.get_mcp_status.assert_called_once()

    @pytest.mark.asyncio
    async def test_failed_server_calls_on_message(self):
        on_msg = AsyncMock()
        session = make_session(on_message=on_msg)
        mock_client = AsyncMock()
        mock_client.get_mcp_status.return_value = {
            "mcpServers": [
                {"name": "bad_server", "status": "failed", "error": "timeout"}
            ]
        }
        session.client = mock_client
        await session._check_mcp_status()
        on_msg.assert_called_once()
        args = on_msg.call_args[0][0]
        assert "bad_server" in args
        assert "[warning]" in args

    @pytest.mark.asyncio
    async def test_disconnected_server_calls_on_message(self):
        on_msg = AsyncMock()
        session = make_session(on_message=on_msg)
        mock_client = AsyncMock()
        mock_client.get_mcp_status.return_value = {
            "mcpServers": [
                {"name": "srv", "status": "disconnected", "error": ""}
            ]
        }
        session.client = mock_client
        await session._check_mcp_status()
        on_msg.assert_called_once()

    @pytest.mark.asyncio
    async def test_needs_auth_server_calls_on_message(self):
        on_msg = AsyncMock()
        session = make_session(on_message=on_msg)
        mock_client = AsyncMock()
        mock_client.get_mcp_status.return_value = {
            "mcpServers": [
                {"name": "auth_srv", "status": "needs-auth", "error": ""}
            ]
        }
        session.client = mock_client
        await session._check_mcp_status()
        on_msg.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_mcp_status_exception_silenced(self):
        session = make_session()
        mock_client = AsyncMock()
        mock_client.get_mcp_status.side_effect = RuntimeError("boom")
        session.client = mock_client
        await session._check_mcp_status()  # Should not raise

    @pytest.mark.asyncio
    async def test_no_on_message_with_failed_server(self):
        # No on_message set — should still not raise
        session = make_session()
        mock_client = AsyncMock()
        mock_client.get_mcp_status.return_value = {
            "mcpServers": [{"name": "x", "status": "failed", "error": "oops"}]
        }
        session.client = mock_client
        await session._check_mcp_status()


# ---------------------------------------------------------------------------
# _receive_loop()
# ---------------------------------------------------------------------------

class TestReceiveLoop:
    def _make_text_message(self, text: str):
        from claude_agent_sdk import AssistantMessage, TextBlock
        block = MagicMock(spec=TextBlock)
        block.text = text
        msg = MagicMock(spec=AssistantMessage)
        msg.content = [block]
        return msg

    def _make_thinking_message(self, thinking: str):
        from claude_agent_sdk import AssistantMessage, ThinkingBlock
        block = MagicMock(spec=ThinkingBlock)
        block.thinking = thinking
        msg = MagicMock(spec=AssistantMessage)
        msg.content = [block]
        return msg

    def _make_tool_use_message(self, name: str, inp: dict):
        from claude_agent_sdk import AssistantMessage, ToolUseBlock
        block = MagicMock(spec=ToolUseBlock)
        block.name = name
        block.input = inp
        msg = MagicMock(spec=AssistantMessage)
        msg.content = [block]
        return msg

    def _make_server_tool_use_message(self, name: str, inp: dict):
        from claude_agent_sdk import AssistantMessage, ServerToolUseBlock
        block = MagicMock(spec=ServerToolUseBlock)
        block.name = name
        block.input = inp
        msg = MagicMock(spec=AssistantMessage)
        msg.content = [block]
        return msg

    def _make_server_tool_result_message(self, content):
        from claude_agent_sdk import AssistantMessage, ServerToolResultBlock
        block = MagicMock(spec=ServerToolResultBlock)
        block.content = content
        msg = MagicMock(spec=AssistantMessage)
        msg.content = [block]
        return msg

    def _make_result_message(self, session_id="sess-1", is_error=False, result_text=None, cost=0.01, usage=None, api_error_status=None):
        from claude_agent_sdk import ResultMessage
        msg = MagicMock(spec=ResultMessage)
        msg.session_id = session_id
        msg.is_error = is_error
        msg.result = result_text
        msg.total_cost_usd = cost
        msg.usage = usage or {}
        msg.api_error_status = api_error_status
        return msg

    async def _run_receive_loop_with_messages(self, session, messages):
        """Helper: patch client.receive_messages to yield given messages, run loop."""
        async def gen():
            for m in messages:
                yield m

        mock_client = AsyncMock()
        # receive_messages must be a regular (non-async) method returning an async iterable
        mock_client.receive_messages = MagicMock(return_value=gen())
        session.client = mock_client
        await session._receive_loop()

    @pytest.mark.asyncio
    async def test_text_block_calls_on_message(self):
        on_msg = AsyncMock()
        session = make_session(on_message=on_msg)
        msg = self._make_text_message("hello world")
        await self._run_receive_loop_with_messages(session, [msg])
        on_msg.assert_called_once_with("hello world")

    @pytest.mark.asyncio
    async def test_thinking_block_calls_on_thinking(self):
        on_thinking = AsyncMock()
        session = make_session(on_thinking=on_thinking)
        msg = self._make_thinking_message("deep thoughts")
        await self._run_receive_loop_with_messages(session, [msg])
        on_thinking.assert_called_once_with("deep thoughts")

    @pytest.mark.asyncio
    async def test_tool_use_block_calls_on_tool_use(self):
        on_tool = AsyncMock()
        session = make_session(on_tool_use=on_tool)
        msg = self._make_tool_use_message("Bash", {"command": "ls"})
        await self._run_receive_loop_with_messages(session, [msg])
        on_tool.assert_called_once_with("Bash", {"command": "ls"})

    @pytest.mark.asyncio
    async def test_result_message_calls_on_complete(self):
        on_complete = AsyncMock()
        session = make_session(on_complete=on_complete)
        msg = self._make_result_message(session_id="s42", is_error=False, cost=0.05)
        await self._run_receive_loop_with_messages(session, [msg])
        on_complete.assert_called_once()
        result_arg = on_complete.call_args[0][0]
        assert isinstance(result_arg, AgentResult)
        assert result_arg.success is True
        assert result_arg.session_id == "s42"
        assert result_arg.cost_usd == 0.05

    @pytest.mark.asyncio
    async def test_result_message_stores_session_id(self):
        session = make_session()
        msg = self._make_result_message(session_id="my-session")
        await self._run_receive_loop_with_messages(session, [msg])
        assert session.current_session_id == "my-session"

    @pytest.mark.asyncio
    async def test_error_result_calls_on_complete_with_error(self):
        on_complete = AsyncMock()
        session = make_session(on_complete=on_complete)
        msg = self._make_result_message(is_error=True, result_text="Something broke")
        await self._run_receive_loop_with_messages(session, [msg])
        result_arg = on_complete.call_args[0][0]
        assert result_arg.success is False
        assert result_arg.error == "Something broke"

    @pytest.mark.asyncio
    async def test_server_tool_use_block_calls_on_tool_use(self):
        on_tool = AsyncMock()
        session = make_session(on_tool_use=on_tool)
        msg = self._make_server_tool_use_message("web_search", {"query": "claude"})
        await self._run_receive_loop_with_messages(session, [msg])
        on_tool.assert_called_once_with("web_search", {"query": "claude"})

    @pytest.mark.asyncio
    async def test_server_tool_result_block_string_content(self):
        on_msg = AsyncMock()
        session = make_session(on_message=on_msg)
        msg = self._make_server_tool_result_message("advisor says hi")
        await self._run_receive_loop_with_messages(session, [msg])
        on_msg.assert_called_once_with("[advisor] advisor says hi")

    @pytest.mark.asyncio
    async def test_server_tool_result_block_list_content_flattened(self):
        on_msg = AsyncMock()
        session = make_session(on_message=on_msg)
        content = [{"text": "first"}, "second", {"content": "third"}]
        msg = self._make_server_tool_result_message(content)
        await self._run_receive_loop_with_messages(session, [msg])
        on_msg.assert_called_once_with("[advisor] first\nsecond\nthird")

    @pytest.mark.asyncio
    async def test_server_tool_result_block_empty_content_no_message(self):
        on_msg = AsyncMock()
        session = make_session(on_message=on_msg)
        msg = self._make_server_tool_result_message("")
        await self._run_receive_loop_with_messages(session, [msg])
        on_msg.assert_not_called()

    @pytest.mark.asyncio
    async def test_error_result_prefixes_http_status(self):
        on_complete = AsyncMock()
        session = make_session(on_complete=on_complete)
        msg = self._make_result_message(
            is_error=True, result_text="Overloaded", api_error_status=529
        )
        await self._run_receive_loop_with_messages(session, [msg])
        result_arg = on_complete.call_args[0][0]
        assert result_arg.success is False
        assert result_arg.api_error_status == 529
        assert result_arg.error == "[HTTP 529] Overloaded"

    @pytest.mark.asyncio
    async def test_success_result_ignores_api_error_status(self):
        on_complete = AsyncMock()
        session = make_session(on_complete=on_complete)
        # Status present but not an error — must not be prefixed, error stays None.
        msg = self._make_result_message(is_error=False, api_error_status=200)
        await self._run_receive_loop_with_messages(session, [msg])
        result_arg = on_complete.call_args[0][0]
        assert result_arg.success is True
        assert result_arg.error is None
        assert result_arg.api_error_status == 200

    @pytest.mark.asyncio
    async def test_error_result_without_status_unprefixed(self):
        on_complete = AsyncMock()
        session = make_session(on_complete=on_complete)
        msg = self._make_result_message(
            is_error=True, result_text="plain failure", api_error_status=None
        )
        await self._run_receive_loop_with_messages(session, [msg])
        result_arg = on_complete.call_args[0][0]
        assert result_arg.error == "plain failure"
        assert result_arg.api_error_status is None

    @pytest.mark.asyncio
    async def test_token_usage_parsed(self):
        on_complete = AsyncMock()
        session = make_session(on_complete=on_complete)
        usage = {"input_tokens": 100, "output_tokens": 50}
        msg = self._make_result_message(usage=usage)
        await self._run_receive_loop_with_messages(session, [msg])
        result_arg = on_complete.call_args[0][0]
        assert result_arg.input_tokens == 100
        assert result_arg.output_tokens == 50
        assert result_arg.total_tokens == 150

    @pytest.mark.asyncio
    async def test_total_tokens_computed_when_missing(self):
        on_complete = AsyncMock()
        session = make_session(on_complete=on_complete)
        # total_tokens not in usage — should be computed
        usage = {"input_tokens": 200, "output_tokens": 75}
        msg = self._make_result_message(usage=usage)
        await self._run_receive_loop_with_messages(session, [msg])
        result_arg = on_complete.call_args[0][0]
        assert result_arg.total_tokens == 275

    @pytest.mark.asyncio
    async def test_exception_calls_on_error(self):
        on_error = AsyncMock()
        session = make_session(on_error=on_error)

        async def gen():
            raise RuntimeError("network error")
            yield  # make it a generator

        mock_client = AsyncMock()
        mock_client.receive_messages = MagicMock(return_value=gen())
        session.client = mock_client
        await session._receive_loop()
        on_error.assert_called_once()
        assert "network error" in on_error.call_args[0][0]

    @pytest.mark.asyncio
    async def test_cancelled_flag_stops_loop(self):
        on_msg = AsyncMock()
        session = make_session(on_message=on_msg)
        session._cancelled = True

        msg = self._make_text_message("should not be seen")

        async def gen():
            yield msg

        mock_client = AsyncMock()
        mock_client.receive_messages = MagicMock(return_value=gen())
        session.client = mock_client
        await session._receive_loop()
        on_msg.assert_not_called()

    @pytest.mark.asyncio
    async def test_client_disconnected_in_finally(self):
        session = make_session()
        mock_client = AsyncMock()
        mock_result = self._make_result_message()

        async def gen():
            yield mock_result

        mock_client.receive_messages = MagicMock(return_value=gen())
        session.client = mock_client
        await session._receive_loop()
        mock_client.disconnect.assert_called_once()
        assert session.client is None

    @pytest.mark.asyncio
    async def test_no_on_message_no_error(self):
        """Receive loop handles missing callbacks gracefully."""
        session = make_session()  # no callbacks
        msg = self._make_text_message("hi")
        await self._run_receive_loop_with_messages(session, [msg])

    @pytest.mark.asyncio
    async def test_system_message_forwarded(self):
        from claude_agent_sdk import SystemMessage
        on_msg = AsyncMock()
        session = make_session(on_message=on_msg)

        sys_msg = MagicMock(spec=SystemMessage)
        sys_msg.content = "progress: 50%"

        async def gen():
            yield sys_msg

        mock_client = AsyncMock()
        mock_client.receive_messages = MagicMock(return_value=gen())
        session.client = mock_client
        await session._receive_loop()
        on_msg.assert_called_once()
        call_text = on_msg.call_args[0][0]
        assert "[system]" in call_text

    @pytest.mark.asyncio
    async def test_empty_thinking_block_not_forwarded(self):
        """ThinkingBlock with empty thinking should NOT call on_thinking."""
        from claude_agent_sdk import AssistantMessage, ThinkingBlock
        on_thinking = AsyncMock()
        session = make_session(on_thinking=on_thinking)

        block = MagicMock(spec=ThinkingBlock)
        block.thinking = ""  # empty — session.py checks `if block.thinking`

        async def gen():
            msg = MagicMock(spec=AssistantMessage)
            msg.content = [block]
            yield msg

        mock_client = AsyncMock()
        mock_client.receive_messages = MagicMock(return_value=gen())
        session.client = mock_client
        await session._receive_loop()
        on_thinking.assert_not_called()


# ---------------------------------------------------------------------------
# start() — options and wiring
# ---------------------------------------------------------------------------

class TestStart:
    @patch("src.agent.session.ClaudeSDKClient")
    @patch("src.agent.session.ClaudeAgentOptions")
    @pytest.mark.asyncio
    async def test_start_creates_client_and_connects(self, mock_options_cls, mock_client_cls, tmp_path):
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        session = make_session(worktree_path=tmp_path)
        try:
            await session.start("Do the thing")
        except Exception:
            pass

        mock_client.connect.assert_called_once()

    @patch("src.agent.session.ClaudeSDKClient")
    @patch("src.agent.session.ClaudeAgentOptions")
    @pytest.mark.asyncio
    async def test_start_calls_query_with_prompt(self, mock_options_cls, mock_client_cls, tmp_path):
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        session = make_session(worktree_path=tmp_path)
        try:
            await session.start("my prompt text")
        except Exception:
            pass

        mock_client.query.assert_called_once()
        prompt_sent = mock_client.query.call_args[0][0]
        assert "my prompt text" in prompt_sent

    @patch("src.agent.session.ClaudeSDKClient")
    @patch("src.agent.session.ClaudeAgentOptions")
    @pytest.mark.asyncio
    async def test_start_passes_cwd_to_options(self, mock_options_cls, mock_client_cls, tmp_path):
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        session = make_session(worktree_path=tmp_path)
        try:
            await session.start("test")
        except Exception:
            pass

        assert mock_options_cls.called
        kwargs = mock_options_cls.call_args.kwargs
        assert kwargs["cwd"] == tmp_path

    @patch("src.agent.session.ClaudeSDKClient")
    @patch("src.agent.session.ClaudeAgentOptions")
    @pytest.mark.asyncio
    async def test_start_passes_model_to_options(self, mock_options_cls, mock_client_cls, tmp_path):
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        session = make_session(worktree_path=tmp_path, model="claude-opus-4")
        try:
            await session.start("test")
        except Exception:
            pass

        kwargs = mock_options_cls.call_args.kwargs
        assert kwargs["model"] == "claude-opus-4"

    @patch("src.agent.session.ClaudeSDKClient")
    @patch("src.agent.session.ClaudeAgentOptions")
    @pytest.mark.asyncio
    async def test_start_sets_resume_options(self, mock_options_cls, mock_client_cls, tmp_path):
        mock_client = AsyncMock()
        mock_options_obj = MagicMock()
        mock_options_cls.return_value = mock_options_obj
        mock_client_cls.return_value = mock_client

        session = make_session(worktree_path=tmp_path)
        try:
            await session.start("resume task", resume_session_id="prev-session-xyz")
        except Exception:
            pass

        assert mock_options_obj.resume == "prev-session-xyz"
        assert mock_options_obj.continue_conversation is True

    @patch("src.agent.session.ClaudeSDKClient")
    @patch("src.agent.session.ClaudeAgentOptions")
    @pytest.mark.asyncio
    async def test_start_permission_mode_accept_edits(self, mock_options_cls, mock_client_cls, tmp_path):
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        session = make_session(worktree_path=tmp_path)
        try:
            await session.start("test")
        except Exception:
            pass

        kwargs = mock_options_cls.call_args.kwargs
        assert kwargs["permission_mode"] == "acceptEdits"

    @patch("src.agent.session.ClaudeSDKClient")
    @patch("src.agent.session.ClaudeAgentOptions")
    @pytest.mark.asyncio
    async def test_start_includes_bash_in_allowed_tools(self, mock_options_cls, mock_client_cls, tmp_path):
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        session = make_session(worktree_path=tmp_path)
        try:
            await session.start("test")
        except Exception:
            pass

        kwargs = mock_options_cls.call_args.kwargs
        allowed = kwargs.get("allowed_tools", [])
        assert "Bash" in allowed

    @patch("src.agent.session.ClaudeSDKClient")
    @patch("src.agent.session.ClaudeAgentOptions")
    @pytest.mark.asyncio
    async def test_start_with_mcp_servers_from_config(self, mock_options_cls, mock_client_cls, tmp_path):
        import json
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        ext_servers = {"my_tool": {"command": "python", "args": ["-m", "my_tool"]}}
        session = make_session(
            worktree_path=tmp_path,
            mcp_enabled=True,
            mcp_servers=json.dumps(ext_servers),
        )
        try:
            await session.start("test")
        except Exception:
            pass

        kwargs = mock_options_cls.call_args.kwargs
        mcp = kwargs.get("mcp_servers") or {}
        assert "my_tool" in mcp

    @patch("src.agent.session.ClaudeSDKClient")
    @patch("src.agent.session.ClaudeAgentOptions")
    @pytest.mark.asyncio
    async def test_start_mcp_disabled_ignores_servers(self, mock_options_cls, mock_client_cls, tmp_path):
        import json
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        ext_servers = {"ignored_tool": {"command": "python"}}
        session = make_session(
            worktree_path=tmp_path,
            mcp_enabled=False,
            mcp_servers=json.dumps(ext_servers),
        )
        try:
            await session.start("test")
        except Exception:
            pass

        kwargs = mock_options_cls.call_args.kwargs
        mcp = kwargs.get("mcp_servers") or {}
        assert "ignored_tool" not in mcp

    @patch("src.agent.session.ClaudeSDKClient")
    @patch("src.agent.session.ClaudeAgentOptions")
    @pytest.mark.asyncio
    async def test_start_system_prompt_augmented(self, mock_options_cls, mock_client_cls, tmp_path):
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        session = make_session(worktree_path=tmp_path, system_prompt="Base instructions.")
        try:
            await session.start("test")
        except Exception:
            pass

        kwargs = mock_options_cls.call_args.kwargs
        sp = kwargs["system_prompt"]
        assert "Base instructions." in sp
        assert str(tmp_path) in sp  # cwd_note injected
        # lifecycle_note: tells the agent completion is automatic, so it doesn't
        # flail trying to "close" the card (the Ollama failure mode).
        assert "AUTOMATICALLY" in sp
        assert "mcp__inloop__" in sp

    @patch("src.agent.session.ClaudeSDKClient")
    @patch("src.agent.session.ClaudeAgentOptions")
    @pytest.mark.asyncio
    async def test_start_injects_own_item_id(self, mock_options_cls, mock_client_cls, tmp_path):
        """When item_id is set, the system prompt tells the agent its own card."""
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        session = make_session(worktree_path=tmp_path, item_id="card-42")
        try:
            await session.start("test")
        except Exception:
            pass

        sp = mock_options_cls.call_args.kwargs["system_prompt"]
        assert "card-42" in sp
        assert "who_am_i" in sp

    @patch("src.agent.session.ClaudeSDKClient")
    @patch("src.agent.session.ClaudeAgentOptions")
    @pytest.mark.asyncio
    async def test_start_omits_item_note_without_item_id(self, mock_options_cls, mock_client_cls, tmp_path):
        """No item_id → no 'YOUR BOARD ITEM' note (back-compat for callers that don't set it)."""
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        session = make_session(worktree_path=tmp_path)
        try:
            await session.start("test")
        except Exception:
            pass

        sp = mock_options_cls.call_args.kwargs["system_prompt"]
        assert "YOUR BOARD ITEM" not in sp

    @patch("src.agent.session.ClaudeSDKClient")
    @patch("src.agent.session.ClaudeAgentOptions")
    @pytest.mark.asyncio
    async def test_start_ollama_gets_stronger_lifecycle_note(self, mock_options_cls, mock_client_cls, tmp_path):
        """Ollama runs get the blunt 'stop calling tools to finish' addendum."""
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        ollama_env = {
            "ANTHROPIC_AUTH_TOKEN": "ollama",
            "ANTHROPIC_API_KEY": "",
            "ANTHROPIC_BASE_URL": "http://localhost:11434",
        }
        session = make_session(worktree_path=tmp_path, model="qwen3.5", ollama_env=ollama_env)
        try:
            await session.start("test")
        except Exception:
            pass

        sp = mock_options_cls.call_args.kwargs["system_prompt"]
        assert "TO FINISH THIS TASK" in sp

    @patch("src.agent.session.ClaudeSDKClient")
    @patch("src.agent.session.ClaudeAgentOptions")
    @pytest.mark.asyncio
    async def test_start_non_ollama_omits_stronger_lifecycle_note(self, mock_options_cls, mock_client_cls, tmp_path):
        """Non-Ollama runs get the general note but not the blunt Ollama addendum."""
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        session = make_session(worktree_path=tmp_path)
        try:
            await session.start("test")
        except Exception:
            pass

        sp = mock_options_cls.call_args.kwargs["system_prompt"]
        assert "AUTOMATICALLY" in sp  # general lifecycle note present
        assert "TO FINISH THIS TASK" not in sp  # Ollama addendum absent

    @patch("src.agent.session.ClaudeSDKClient")
    @patch("src.agent.session.ClaudeAgentOptions")
    @pytest.mark.asyncio
    async def test_start_clarification_server_registered_when_callback(self, mock_options_cls, mock_client_cls, tmp_path):
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        session = make_session(worktree_path=tmp_path, on_clarify=AsyncMock())
        try:
            await session.start("test")
        except Exception:
            pass

        kwargs = mock_options_cls.call_args.kwargs
        mcp = kwargs.get("mcp_servers") or {}
        assert "clarification" in mcp

    @patch("src.agent.session.ClaudeSDKClient")
    @patch("src.agent.session.ClaudeAgentOptions")
    @pytest.mark.asyncio
    async def test_start_no_clarification_server_without_callback(self, mock_options_cls, mock_client_cls, tmp_path):
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        session = make_session(worktree_path=tmp_path)  # no on_clarify
        try:
            await session.start("test")
        except Exception:
            pass

        kwargs = mock_options_cls.call_args.kwargs
        mcp = kwargs.get("mcp_servers") or {}
        assert "clarification" not in mcp

    @patch("src.agent.session.ClaudeSDKClient")
    @patch("src.agent.session.ClaudeAgentOptions")
    @pytest.mark.asyncio
    async def test_start_sets_setting_sources(self, mock_options_cls, mock_client_cls, tmp_path):
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        session = make_session(worktree_path=tmp_path)
        try:
            await session.start("test")
        except Exception:
            pass

        kwargs = mock_options_cls.call_args.kwargs
        assert kwargs.get("setting_sources") == ["project"]

    @patch("src.agent.session.ClaudeSDKClient")
    @patch("src.agent.session.ClaudeAgentOptions")
    @pytest.mark.asyncio
    async def test_start_ollama_excludes_user_settings(self, mock_options_cls, mock_client_cls, tmp_path):
        """Ollama runs must NOT load `user` settings, or global PreToolUse hooks
        (e.g. the RTK command-rewriter) leak in and mangle command output."""
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        ollama_env = {
            "ANTHROPIC_AUTH_TOKEN": "ollama",
            "ANTHROPIC_API_KEY": "",
            "ANTHROPIC_BASE_URL": "http://localhost:11434",
        }
        session = make_session(worktree_path=tmp_path, model="qwen3.5", ollama_env=ollama_env)
        try:
            await session.start("test")
        except Exception:
            pass

        kwargs = mock_options_cls.call_args.kwargs
        sources = kwargs.get("setting_sources")
        assert sources is not None, "Ollama must pass an explicit setting_sources to exclude user hooks"
        assert "user" not in sources

    @patch("src.agent.session.ClaudeSDKClient")
    @patch("src.agent.session.ClaudeAgentOptions")
    @pytest.mark.asyncio
    async def test_start_ollama_disables_thinking(self, mock_options_cls, mock_client_cls, tmp_path):
        """Ollama returns unsigned thinking blocks that crash on replay, so
        thinking must be explicitly disabled."""
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        ollama_env = {
            "ANTHROPIC_AUTH_TOKEN": "ollama",
            "ANTHROPIC_API_KEY": "",
            "ANTHROPIC_BASE_URL": "http://localhost:11434",
        }
        session = make_session(worktree_path=tmp_path, model="qwen3.5", ollama_env=ollama_env)
        try:
            await session.start("test")
        except Exception:
            pass

        kwargs = mock_options_cls.call_args.kwargs
        assert kwargs.get("thinking") == {"type": "disabled"}

    @patch("src.agent.session.ClaudeSDKClient")
    @patch("src.agent.session.ClaudeAgentOptions")
    @pytest.mark.asyncio
    async def test_start_ollama_injects_claude_md_when_enabled(self, mock_options_cls, mock_client_cls, tmp_path):
        """With ollama_load_claude_md on, the worktree CLAUDE.md is injected
        into the system prompt (the Ollama path's setting_sources=['local']
        does not auto-load it)."""
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        (tmp_path / "CLAUDE.md").write_text("PROJECT CONVENTIONS: use tabs.")

        ollama_env = {"ANTHROPIC_AUTH_TOKEN": "ollama", "ANTHROPIC_API_KEY": "",
                      "ANTHROPIC_BASE_URL": "http://localhost:11434"}
        session = make_session(worktree_path=tmp_path, model="qwen3.5",
                               ollama_env=ollama_env, ollama_load_claude_md=True)
        try:
            await session.start("test")
        except Exception:
            pass

        sp = mock_options_cls.call_args.kwargs["system_prompt"]
        assert "PROJECT CONVENTIONS: use tabs." in sp
        assert "Project CLAUDE.md" in sp

    @patch("src.agent.session.ClaudeSDKClient")
    @patch("src.agent.session.ClaudeAgentOptions")
    @pytest.mark.asyncio
    async def test_start_ollama_omits_claude_md_by_default(self, mock_options_cls, mock_client_cls, tmp_path):
        """Default (toggle off): CLAUDE.md is NOT injected, keeping context lean."""
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        (tmp_path / "CLAUDE.md").write_text("PROJECT CONVENTIONS: use tabs.")

        ollama_env = {"ANTHROPIC_AUTH_TOKEN": "ollama", "ANTHROPIC_API_KEY": "",
                      "ANTHROPIC_BASE_URL": "http://localhost:11434"}
        session = make_session(worktree_path=tmp_path, model="qwen3.5",
                               ollama_env=ollama_env)
        try:
            await session.start("test")
        except Exception:
            pass

        sp = mock_options_cls.call_args.kwargs["system_prompt"]
        assert "PROJECT CONVENTIONS: use tabs." not in sp

    @patch("src.agent.session.ClaudeSDKClient")
    @patch("src.agent.session.ClaudeAgentOptions")
    @pytest.mark.asyncio
    async def test_start_non_ollama_ignores_claude_md_flag(self, mock_options_cls, mock_client_cls, tmp_path):
        """The flag only affects Ollama runs; Claude runs auto-load CLAUDE.md via
        setting_sources=['project'] and must not double-inject it."""
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        (tmp_path / "CLAUDE.md").write_text("PROJECT CONVENTIONS: use tabs.")

        session = make_session(worktree_path=tmp_path, model="claude-opus-4-8",
                               ollama_load_claude_md=True)
        try:
            await session.start("test")
        except Exception:
            pass

        sp = mock_options_cls.call_args.kwargs["system_prompt"]
        assert "PROJECT CONVENTIONS: use tabs." not in sp

    @patch("src.agent.session.ClaudeSDKClient")
    @patch("src.agent.session.ClaudeAgentOptions")
    @pytest.mark.asyncio
    async def test_start_passes_ollama_env_to_options(self, mock_options_cls, mock_client_cls, tmp_path):
        """Ollama env vars are forwarded to ClaudeAgentOptions.env."""
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        ollama_env = {
            "ANTHROPIC_AUTH_TOKEN": "ollama",
            "ANTHROPIC_API_KEY": "",
            "ANTHROPIC_BASE_URL": "http://localhost:11434",
        }
        session = make_session(worktree_path=tmp_path, model="qwen3.5", ollama_env=ollama_env)
        try:
            await session.start("test")
        except Exception:
            pass

        kwargs = mock_options_cls.call_args.kwargs
        assert kwargs["env"] == ollama_env
        assert kwargs["model"] == "qwen3.5"

    @patch("src.agent.session.ClaudeSDKClient")
    @patch("src.agent.session.ClaudeAgentOptions")
    @pytest.mark.asyncio
    async def test_start_ollama_env_none_passes_empty_dict(self, mock_options_cls, mock_client_cls, tmp_path):
        """When ollama_env is None, env should be an empty dict (SDK default)."""
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        session = make_session(worktree_path=tmp_path)
        try:
            await session.start("test")
        except Exception:
            pass

        kwargs = mock_options_cls.call_args.kwargs
        assert kwargs["env"] == {}

    @patch("src.agent.session.ClaudeSDKClient")
    @patch("src.agent.session.ClaudeAgentOptions")
    @pytest.mark.asyncio
    async def test_start_ollama_env_custom_base_url(self, mock_options_cls, mock_client_cls, tmp_path):
        """Ollama running on a custom host/port is forwarded correctly."""
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        ollama_env = {
            "ANTHROPIC_AUTH_TOKEN": "ollama",
            "ANTHROPIC_API_KEY": "",
            "ANTHROPIC_BASE_URL": "http://192.168.1.100:11434",
        }
        session = make_session(worktree_path=tmp_path, model="llama3.2", ollama_env=ollama_env)
        try:
            await session.start("test")
        except Exception:
            pass

        kwargs = mock_options_cls.call_args.kwargs
        assert kwargs["env"]["ANTHROPIC_BASE_URL"] == "http://192.168.1.100:11434"
        assert kwargs["model"] == "llama3.2"


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
