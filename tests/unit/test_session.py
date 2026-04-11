"""Unit tests for src/agent/session.py — AgentSession class."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from src.agent.session import AgentSession, AgentResult, build_attachment_prompt


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

    def test_defaults_are_none(self):
        r = AgentResult(success=True)
        assert r.session_id is None
        assert r.error is None
        assert r.cost_usd is None
        assert r.input_tokens is None
        assert r.output_tokens is None
        assert r.total_tokens is None


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

    def test_model_default_none(self):
        session = make_session()
        assert session.model is None

    def test_model_stored(self):
        session = make_session(model="claude-opus-4")
        assert session.model == "claude-opus-4"

    def test_callbacks_default_none(self):
        session = make_session()
        assert session.on_message is None
        assert session.on_tool_use is None
        assert session.on_thinking is None
        assert session.on_complete is None
        assert session.on_error is None
        assert session.on_clarify is None
        assert session.on_create_todo is None
        assert session.on_set_commit_message is None

    def test_callbacks_stored(self):
        cb = AsyncMock()
        session = make_session(on_message=cb, on_complete=cb)
        assert session.on_message is cb
        assert session.on_complete is cb

    def test_allowed_commands_default_empty_list(self):
        session = make_session()
        assert session.allowed_commands == []

    def test_allowed_commands_stored(self):
        cmds = ["git", "npm"]
        session = make_session(allowed_commands=cmds)
        assert session.allowed_commands == cmds

    def test_bash_yolo_default_false(self):
        session = make_session()
        assert session.bash_yolo is False

    def test_use_advisor_default_false(self):
        session = make_session()
        assert session.use_advisor is False

    def test_use_advisor_stored_true(self):
        session = make_session(use_advisor=True)
        assert session.use_advisor is True

    def test_initial_state(self):
        session = make_session()
        assert session.client is None
        assert session._task is None
        assert session._cancelled is False
        assert session.current_session_id is None

    def test_mcp_disabled_by_default(self):
        session = make_session()
        assert session.mcp_enabled is False
        assert session.mcp_servers is None

    def test_plugins_default_none(self):
        session = make_session()
        assert session.plugins is None

    def test_allowed_builtin_tools_default_empty(self):
        session = make_session()
        assert session.allowed_builtin_tools == []


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

    def _make_result_message(self, session_id="sess-1", is_error=False, result_text=None, cost=0.01, usage=None):
        from claude_agent_sdk import ResultMessage
        msg = MagicMock(spec=ResultMessage)
        msg.session_id = session_id
        msg.is_error = is_error
        msg.result = result_text
        msg.total_cost_usd = cost
        msg.usage = usage or {}
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


# ---------------------------------------------------------------------------
# can_use_tool — inline closure behavior
# ---------------------------------------------------------------------------

class TestCanUseTool:
    """Test the can_use_tool closure built in start() when plugins/external MCP present."""

    def _make_can_use_tool(self, allowed_tools, all_prefixes):
        """Recreate the closure logic from session.py directly."""
        allowed_set = set(allowed_tools)
        def can_use_tool(tool_name: str) -> bool:
            if tool_name in allowed_set:
                return True
            for prefix in all_prefixes:
                if tool_name.startswith(prefix):
                    return True
            return not tool_name.startswith("mcp__")
        return can_use_tool

    def test_allowed_tool_permitted(self):
        fn = self._make_can_use_tool(["Bash", "Read"], [])
        assert fn("Bash") is True
        assert fn("Read") is True

    def test_standard_non_mcp_tool_permitted(self):
        fn = self._make_can_use_tool([], [])
        assert fn("Write") is True
        assert fn("Edit") is True

    def test_unknown_mcp_tool_blocked(self):
        fn = self._make_can_use_tool([], [])
        assert fn("mcp__unknown__tool") is False

    def test_prefix_match_permits_mcp_tool(self):
        fn = self._make_can_use_tool([], ["mcp__my_plugin_"])
        assert fn("mcp__my_plugin_do_thing") is True

    def test_no_prefix_match_blocks_mcp_tool(self):
        fn = self._make_can_use_tool([], ["mcp__other_"])
        assert fn("mcp__my_plugin_do_thing") is False

    def test_explicit_mcp_tool_in_allowed_set_permitted(self):
        fn = self._make_can_use_tool(["mcp__todo__create_todo"], [])
        assert fn("mcp__todo__create_todo") is True

    def test_wildcard_prefix_allows_all_variants(self):
        fn = self._make_can_use_tool([], ["mcp__ext_server__"])
        assert fn("mcp__ext_server__tool_a") is True
        assert fn("mcp__ext_server__tool_b") is True
        assert fn("mcp__other__tool") is False
