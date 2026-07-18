"""Unit tests for src/agent/kimi_session.py — KimiAgentSession over ACP (experimental)."""

import asyncio
import os
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.agent.base import AbstractAgentSession, AgentResult
from src.agent.kimi_session import (
    KIMI_SDK_INSTALL_HINT,
    KimiAgentSession,
    _PendingToolCall,
    _content_text,
    _decide_permission,
    _extract_ask_user,
    _extract_commit_message,
    _project_context_note,
    _raw_input,
)


def make_acp_module(session_id="acp-1", load_raises=None):
    """Build a fake `kimi_agent_sdk.acp` module.

    Returns (sys.modules patch dict, module, items list). Append updates to
    the items list using the module's own classes so isinstance checks in the
    code under test match. "HANG" sleeps forever; an Exception instance is
    raised mid-stream.
    """
    items = []
    mod = types.ModuleType("kimi_agent_sdk.acp")

    class TextContent:
        def __init__(self, text):
            self.text = text

    class AgentMessageChunk:
        def __init__(self, content):
            self.content = content

    class AgentThoughtChunk:
        def __init__(self, content):
            self.content = content

    class ToolCallStart:
        def __init__(self, title, kind=None, raw=None, tool_call_id="tc-1"):
            self.tool_call_id = tool_call_id
            self.title = title
            self.kind = kind
            self.status = None
            self.raw = raw or {}

    class ToolCallProgress:
        def __init__(self, tool_call_id="tc-1", status=None, raw=None):
            self.tool_call_id = tool_call_id
            self.status = status
            self.raw = raw or {}

    class TurnEnded:
        def __init__(self, stop_reason):
            self.stop_reason = stop_reason

    class PermissionSelected:
        def __init__(self, option_id):
            self.option_id = option_id

    class PermissionCancelled:
        pass

    class FakeAcpSession:
        def __init__(self):
            self.id = session_id
            self.prompts = []
            self.cancelled = False
            self._turn = 0

        async def prompt(self, user_input):
            self.prompts.append(user_input)
            # Turn mode: when items is a list of lists, each prompt() call
            # consumes the next sub-list. Flat lists replay every call.
            if items and isinstance(items[0], list):
                turn_items = items[self._turn] if self._turn < len(items) else []
                self._turn += 1
            else:
                turn_items = items
            for item in turn_items:
                if item == "HANG":
                    await asyncio.sleep(30)
                elif isinstance(item, Exception):
                    raise item
                else:
                    yield item

        async def cancel(self):
            self.cancelled = True

    class FakeConnection:
        def __init__(self):
            self.requests = []

        async def request(self, method, params):
            self.requests.append((method, params))
            return {}

    class AcpClient:
        last = None

        def __init__(self):
            self.connect_kwargs = None
            self.session = FakeAcpSession()
            self.connection = FakeConnection()
            self.new_session_calls = []
            self.load_session_calls = []
            self.closed = False

        @classmethod
        async def connect(cls, **kwargs):
            client = cls()
            client.connect_kwargs = kwargs
            cls.last = client
            return client

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            self.closed = True

        async def new_session(self, cwd=None, **kwargs):
            self.new_session_calls.append(cwd)
            self.new_session_kwargs = kwargs
            return self.session

        async def load_session(self, sid, cwd=None, **kwargs):
            self.load_session_calls.append((sid, cwd))
            if load_raises is not None:
                raise load_raises
            self.session.id = sid
            return self.session

    for cls in (TextContent, AgentMessageChunk, AgentThoughtChunk,
                ToolCallStart, ToolCallProgress, TurnEnded, AcpClient,
                PermissionSelected, PermissionCancelled):
        setattr(mod, cls.__name__, cls)
    pkg = types.ModuleType("kimi_agent_sdk")
    pkg.acp = mod
    return {"kimi_agent_sdk": pkg, "kimi_agent_sdk.acp": mod}, mod, items


def make_session(**kwargs):
    defaults = dict(
        worktree_path=Path("/tmp/test-worktree"),
        system_prompt="You are a helpful agent.",
        model="kimi-k2",
    )
    defaults.update(kwargs)
    return KimiAgentSession(**defaults)


async def start_and_wait(session, prompt="do the task", **start_kwargs):
    await session.start(prompt, **start_kwargs)
    await session._task


class TestContract:
    def test_implements_abstract_session(self):
        assert issubclass(KimiAgentSession, AbstractAgentSession)

    def test_initial_state(self):
        s = make_session()
        assert s.current_session_id is None
        assert s._task is None


class TestHelpers:
    def test_content_text_reads_text_attr(self):
        assert _content_text(types.SimpleNamespace(text="hi")) == "hi"

    def test_content_text_empty_for_non_text_blocks(self):
        assert _content_text(types.SimpleNamespace(data=b"...")) == ""

    def test_raw_input_extracts_dict(self):
        assert _raw_input(types.SimpleNamespace(raw={"rawInput": {"path": "a.py"}})) == {"path": "a.py"}

    def test_raw_input_none_when_absent(self):
        assert _raw_input(types.SimpleNamespace(raw={})) is None

    def test_pending_tool_call_input_merges_kind(self):
        start = types.SimpleNamespace(tool_call_id="tc", title="Read", kind="read",
                                      raw={"rawInput": {"path": "a.py"}})
        assert _PendingToolCall(start).input == {"path": "a.py", "kind": "read"}

    def test_pending_tool_call_merge_progress_takes_input_and_title(self):
        start = types.SimpleNamespace(tool_call_id="tc", title="Tool", kind=None, raw={})
        pending = _PendingToolCall(start)
        pending.merge_progress(types.SimpleNamespace(
            raw={"title": "Edit app.py", "rawInput": {"path": "app.py"}}))
        assert pending.title == "Edit app.py"
        assert pending.input == {"path": "app.py"}


class TestRun:
    @pytest.mark.asyncio
    async def test_aggregates_chunks_and_completes(self):
        on_message = AsyncMock()
        on_tool_use = AsyncMock()
        on_thinking = AsyncMock()
        on_complete = AsyncMock()
        modules, acp, items = make_acp_module()
        T = acp.TextContent
        items.extend([
            acp.AgentThoughtChunk(T("hmm ")), acp.AgentThoughtChunk(T("ok")),
            acp.AgentMessageChunk(T("Hello ")), acp.AgentMessageChunk(T("world")),
            acp.ToolCallStart("Read file", kind="read", raw={"rawInput": {"path": "a.py"}}),
            acp.AgentMessageChunk(T("done")),
            acp.TurnEnded("end_turn"),
        ])
        session = make_session(on_message=on_message, on_tool_use=on_tool_use,
                               on_thinking=on_thinking, on_complete=on_complete)
        with patch.dict(sys.modules, modules):
            await start_and_wait(session)

        on_thinking.assert_awaited_once_with("hmm ok")
        assert [c.args[0] for c in on_message.call_args_list] == ["Hello world", "done"]
        on_tool_use.assert_awaited_once_with("Read file", {"path": "a.py", "kind": "read"})
        result = on_complete.call_args.args[0]
        assert isinstance(result, AgentResult) and result.success is True
        assert result.session_id == "acp-1"
        assert session.current_session_id == "acp-1"

    @pytest.mark.asyncio
    async def test_model_env_and_prompt_composition(self):
        modules, acp, items = make_acp_module()
        session = make_session()
        with patch.dict(sys.modules, modules):
            await start_and_wait(session, "fix the bug")
        client = acp.AcpClient.last
        assert client.connect_kwargs["yolo"] is False
        assert callable(client.connect_kwargs["permission_handler"])
        assert client.connect_kwargs["env"]["KIMI_MODEL_NAME"] == "kimi-k2"
        assert client.new_session_calls == [Path("/tmp/test-worktree")]
        assert ("session/set_config_option",
                {"sessionId": "acp-1", "configId": "model", "value": "kimi-k2"}
                ) in client.connection.requests
        sent = client.session.prompts[0]
        assert "You are a helpful agent." in sent
        assert "/tmp/test-worktree" in sent
        assert "fix the bug" in sent
        assert client.closed is True

    @pytest.mark.asyncio
    async def test_missing_sdk_reports_install_hint(self):
        on_error = AsyncMock()
        on_complete = AsyncMock()
        session = make_session(on_error=on_error, on_complete=on_complete)
        with patch.dict(sys.modules, {"kimi_agent_sdk": None, "kimi_agent_sdk.acp": None}):
            await start_and_wait(session)
        on_error.assert_awaited_once_with(KIMI_SDK_INSTALL_HINT)
        on_complete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_abnormal_stop_reason_reports_error(self):
        on_error = AsyncMock()
        on_complete = AsyncMock()
        modules, acp, items = make_acp_module()
        items.append(acp.TurnEnded("max_tokens"))
        session = make_session(on_error=on_error, on_complete=on_complete)
        with patch.dict(sys.modules, modules):
            await start_and_wait(session)
        on_error.assert_awaited_once_with("Kimi run stopped early: max_tokens")
        on_complete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stream_error_reported_via_on_error(self):
        on_error = AsyncMock()
        on_complete = AsyncMock()
        modules, acp, items = make_acp_module()
        items.append(RuntimeError("agent exploded"))
        session = make_session(on_error=on_error, on_complete=on_complete)
        with patch.dict(sys.modules, modules):
            await start_and_wait(session)
        on_error.assert_awaited_once_with("agent exploded")
        on_complete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cancel_requests_acp_cancel_and_stops(self):
        on_complete = AsyncMock()
        modules, acp, items = make_acp_module()
        items.append("HANG")
        session = make_session(on_complete=on_complete)
        with patch.dict(sys.modules, modules):
            await session.start("task")
            await asyncio.sleep(0.05)
            await session.cancel()
        client = acp.AcpClient.last
        assert client.session.cancelled is True
        assert session._task.done()
        on_complete.assert_not_awaited()
        assert client.closed is True


class TestExtractCommitMessage:
    def test_extracts_and_strips_line(self):
        text, msg = _extract_commit_message("All done.\nCOMMIT_MESSAGE: Add farewell function")
        assert msg == "Add farewell function"
        assert text == "All done."

    def test_no_line_returns_text_unchanged(self):
        text, msg = _extract_commit_message("Just a normal message")
        assert msg is None
        assert text == "Just a normal message"

    def test_last_line_wins_when_repeated(self):
        text, msg = _extract_commit_message(
            "COMMIT_MESSAGE: first try\nmore work\nCOMMIT_MESSAGE: final version"
        )
        assert msg == "final version"
        assert "COMMIT_MESSAGE" not in text

    def test_indented_line_and_trailing_space(self):
        _, msg = _extract_commit_message("done\n  COMMIT_MESSAGE:  Fix the bug  ")
        assert msg == "Fix the bug"


class TestCommitMessageFlow:
    @pytest.mark.asyncio
    async def test_commit_line_routed_to_callback_and_stripped_from_log(self):
        on_message = AsyncMock()
        on_set_commit_message = AsyncMock()
        modules, acp, items = make_acp_module()
        T = acp.TextContent
        items.extend([
            acp.AgentMessageChunk(T("Added the function.\n")),
            acp.AgentMessageChunk(T("COMMIT_MESSAGE: Add farewell function")),
            acp.TurnEnded("end_turn"),
        ])
        session = make_session(on_message=on_message,
                               on_set_commit_message=on_set_commit_message)
        with patch.dict(sys.modules, modules):
            await start_and_wait(session)
        on_set_commit_message.assert_awaited_once_with("Add farewell function")
        on_message.assert_awaited_once_with("Added the function.")

    @pytest.mark.asyncio
    async def test_commit_only_message_skips_empty_on_message(self):
        on_message = AsyncMock()
        on_set_commit_message = AsyncMock()
        modules, acp, items = make_acp_module()
        items.extend([
            acp.AgentMessageChunk(acp.TextContent("COMMIT_MESSAGE: Tiny fix")),
            acp.TurnEnded("end_turn"),
        ])
        session = make_session(on_message=on_message,
                               on_set_commit_message=on_set_commit_message)
        with patch.dict(sys.modules, modules):
            await start_and_wait(session)
        on_set_commit_message.assert_awaited_once_with("Tiny fix")
        on_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_prompt_carries_instruction_only_with_callback(self):
        modules, acp, items = make_acp_module()
        session = make_session(on_set_commit_message=AsyncMock())
        with patch.dict(sys.modules, modules):
            await start_and_wait(session)
        assert "COMMIT_MESSAGE:" in acp.AcpClient.last.session.prompts[0]

        modules2, acp2, _ = make_acp_module()
        session2 = make_session()
        with patch.dict(sys.modules, modules2):
            await start_and_wait(session2)
        assert "COMMIT_MESSAGE:" not in acp2.AcpClient.last.session.prompts[0]

    @pytest.mark.asyncio
    async def test_text_without_callback_passes_through_untouched(self):
        on_message = AsyncMock()
        modules, acp, items = make_acp_module()
        items.extend([
            acp.AgentMessageChunk(acp.TextContent("COMMIT_MESSAGE: not parsed")),
            acp.TurnEnded("end_turn"),
        ])
        session = make_session(on_message=on_message)
        with patch.dict(sys.modules, modules):
            await start_and_wait(session)
        on_message.assert_awaited_once_with("COMMIT_MESSAGE: not parsed")


class TestExtractAskUser:
    def test_extracts_and_strips_line(self):
        text, q = _extract_ask_user("I need input.\nASK_USER: Which database should I use?")
        assert q == "Which database should I use?"
        assert text == "I need input."

    def test_no_line_returns_none(self):
        text, q = _extract_ask_user("No questions here")
        assert q is None
        assert text == "No questions here"


class TestAskUserFlow:
    @pytest.mark.asyncio
    async def test_question_blocks_on_clarify_then_continues_with_answer(self):
        on_message = AsyncMock()
        on_clarify = AsyncMock(return_value="Use SQLite")
        on_complete = AsyncMock()
        modules, acp, items = make_acp_module()
        T = acp.TextContent
        items.append([  # turn 1: agent asks
            acp.AgentMessageChunk(T("I checked the repo.\nASK_USER: Which database should I use?")),
            acp.TurnEnded("end_turn"),
        ])
        items.append([  # turn 2: agent finishes with the answer in hand
            acp.AgentMessageChunk(T("Done, used SQLite.")),
            acp.TurnEnded("end_turn"),
        ])
        session = make_session(on_message=on_message, on_clarify=on_clarify,
                               on_complete=on_complete)
        with patch.dict(sys.modules, modules):
            await start_and_wait(session)

        on_clarify.assert_awaited_once_with("Which database should I use?", None)
        client = acp.AcpClient.last
        assert len(client.session.prompts) == 2
        assert client.session.prompts[1] == "User's answer: Use SQLite"
        assert [c.args[0] for c in on_message.call_args_list] == [
            "I checked the repo.", "Done, used SQLite."]
        on_complete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_multiple_questions_chain_turns(self):
        on_clarify = AsyncMock(side_effect=["answer one", "answer two"])
        on_complete = AsyncMock()
        modules, acp, items = make_acp_module()
        T = acp.TextContent
        items.append([acp.AgentMessageChunk(T("ASK_USER: first?")), acp.TurnEnded("end_turn")])
        items.append([acp.AgentMessageChunk(T("ASK_USER: second?")), acp.TurnEnded("end_turn")])
        items.append([acp.AgentMessageChunk(T("done")), acp.TurnEnded("end_turn")])
        session = make_session(on_clarify=on_clarify, on_complete=on_complete)
        with patch.dict(sys.modules, modules):
            await start_and_wait(session)
        assert on_clarify.await_count == 2
        assert len(acp.AcpClient.last.session.prompts) == 3
        on_complete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_prompt_carries_instruction_only_with_callback(self):
        modules, acp, _ = make_acp_module()
        session = make_session(on_clarify=AsyncMock(return_value="x"))
        with patch.dict(sys.modules, modules):
            await start_and_wait(session)
        assert "ASK_USER:" in acp.AcpClient.last.session.prompts[0]

        modules2, acp2, _ = make_acp_module()
        session2 = make_session()
        with patch.dict(sys.modules, modules2):
            await start_and_wait(session2)
        assert "ASK_USER:" not in acp2.AcpClient.last.session.prompts[0]

    @pytest.mark.asyncio
    async def test_question_without_callback_passes_through(self):
        on_message = AsyncMock()
        on_complete = AsyncMock()
        modules, acp, items = make_acp_module()
        items.extend([
            acp.AgentMessageChunk(acp.TextContent("ASK_USER: ignored?")),
            acp.TurnEnded("end_turn"),
        ])
        session = make_session(on_message=on_message, on_complete=on_complete)
        with patch.dict(sys.modules, modules):
            await start_and_wait(session)
        on_message.assert_awaited_once_with("ASK_USER: ignored?")
        on_complete.assert_awaited_once()


class TestDeferredToolInput:
    @pytest.mark.asyncio
    async def test_input_from_later_progress_update(self):
        on_tool_use = AsyncMock()
        modules, acp, items = make_acp_module()
        items.extend([
            acp.ToolCallStart("Edit", kind="edit"),  # kimi-code: no rawInput here
            acp.ToolCallProgress(raw={"rawInput": {"path": "app.py"}}),
            acp.TurnEnded("end_turn"),
        ])
        session = make_session(on_tool_use=on_tool_use)
        with patch.dict(sys.modules, modules):
            await start_and_wait(session)
        on_tool_use.assert_awaited_once_with("Edit", {"path": "app.py", "kind": "edit"})

    @pytest.mark.asyncio
    async def test_completed_status_emits_even_without_input(self):
        on_tool_use = AsyncMock()
        modules, acp, items = make_acp_module()
        items.extend([
            acp.ToolCallStart("Bash", kind="execute"),
            acp.ToolCallProgress(status="completed"),
            acp.TurnEnded("end_turn"),
        ])
        session = make_session(on_tool_use=on_tool_use)
        with patch.dict(sys.modules, modules):
            await start_and_wait(session)
        on_tool_use.assert_awaited_once_with("Bash", {"kind": "execute"})

    @pytest.mark.asyncio
    async def test_pending_flushed_by_next_tool_and_turn_end(self):
        on_tool_use = AsyncMock()
        modules, acp, items = make_acp_module()
        items.extend([
            acp.ToolCallStart("Read", kind="read", tool_call_id="tc-1"),
            acp.ToolCallStart("Grep", kind="search", tool_call_id="tc-2"),
            acp.TurnEnded("end_turn"),
        ])
        session = make_session(on_tool_use=on_tool_use)
        with patch.dict(sys.modules, modules):
            await start_and_wait(session)
        assert [c.args for c in on_tool_use.call_args_list] == [
            ("Read", {"kind": "read"}),
            ("Grep", {"kind": "search"}),
        ]

    @pytest.mark.asyncio
    async def test_no_duplicate_emission_when_start_has_input(self):
        on_tool_use = AsyncMock()
        modules, acp, items = make_acp_module()
        items.extend([
            acp.ToolCallStart("Read", kind="read", raw={"rawInput": {"path": "a.py"}}),
            acp.ToolCallProgress(status="completed", raw={"rawInput": {"path": "a.py"}}),
            acp.TurnEnded("end_turn"),
        ])
        session = make_session(on_tool_use=on_tool_use)
        with patch.dict(sys.modules, modules):
            await start_and_wait(session)
        on_tool_use.assert_awaited_once_with("Read", {"path": "a.py", "kind": "read"})


class TestDecidePermission:
    def test_non_execute_kind_allowed(self):
        assert _decide_permission({"kind": "read", "rawInput": {"path": "a.py"}}, [], False) == ("allow", "")

    def test_bash_yolo_allows_everything(self):
        decision, cmd = _decide_permission(
            {"kind": "execute", "rawInput": {"command": "rm -rf build"}}, [], True)
        assert decision == "allow" and cmd == "rm -rf build"

    def test_allowlisted_first_word_allowed(self):
        decision, _ = _decide_permission(
            {"kind": "execute", "rawInput": {"command": "npm install"}}, ["npm"], False)
        assert decision == "allow"

    def test_shell_operator_escalates_even_when_allowlisted(self):
        decision, _ = _decide_permission(
            {"kind": "execute", "rawInput": {"command": "ls && rm -rf /"}}, ["ls"], False)
        assert decision == "ask"

    def test_unlisted_command_escalates(self):
        decision, cmd = _decide_permission(
            {"kind": "execute", "rawInput": {"command": "curl http://x"}}, ["npm"], False)
        assert decision == "ask" and cmd == "curl http://x"

    def test_execute_without_raw_input_uses_title(self):
        decision, cmd = _decide_permission(
            {"kind": "execute", "title": "mystery"}, [], False)
        assert decision == "ask" and cmd == "mystery"

    def test_none_tool_call_allowed(self):
        assert _decide_permission(None, [], False) == ("allow", "")

    def test_force_ask_env_escalates_even_allowlisted_and_yolo(self):
        tc = {"kind": "execute", "rawInput": {"command": "npm test"}}
        with patch.dict(os.environ, {"KIMI_FORCE_PERMISSION_ASK": "1"}):
            assert _decide_permission(tc, ["npm"], False)[0] == "ask"
            assert _decide_permission(tc, [], True)[0] == "ask"

    def test_force_ask_env_leaves_non_execute_allowed(self):
        tc = {"kind": "read", "rawInput": {"path": "a.py"}}
        with patch.dict(os.environ, {"KIMI_FORCE_PERMISSION_ASK": "1"}):
            assert _decide_permission(tc, [], False) == ("allow", "")


class TestProjectContextNote:
    def test_injects_claude_md_when_no_agents_md(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("Use tabs, always.")
        note = _project_context_note(tmp_path)
        assert "Use tabs, always." in note
        assert "Project CLAUDE.md" in note

    def test_skipped_when_agents_md_exists(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("claude conventions")
        (tmp_path / "AGENTS.md").write_text("agents conventions")
        assert _project_context_note(tmp_path) == ""

    def test_skipped_when_dot_kimi_agents_md_exists(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("claude conventions")
        (tmp_path / ".kimi").mkdir()
        (tmp_path / ".kimi" / "AGENTS.md").write_text("kimi conventions")
        assert _project_context_note(tmp_path) == ""

    def test_empty_when_no_context_files(self, tmp_path):
        assert _project_context_note(tmp_path) == ""

    @pytest.mark.asyncio
    async def test_claude_md_reaches_the_prompt(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("Use tabs, always.")
        modules, acp, _ = make_acp_module()
        session = make_session(worktree_path=tmp_path)
        with patch.dict(sys.modules, modules):
            await start_and_wait(session)
        assert "Use tabs, always." in acp.AcpClient.last.session.prompts[0]


def make_permission_request(command="curl http://x", kind="execute", options=None):
    opts = options if options is not None else [
        types.SimpleNamespace(option_id="a1", name="Allow", kind="allow_once"),
        types.SimpleNamespace(option_id="r1", name="Reject", kind="reject_once"),
    ]
    return types.SimpleNamespace(
        session_id="s", options=tuple(opts),
        tool_call={"kind": kind, "rawInput": {"command": command}, "title": command},
    )


class TestPermissionHandler:
    async def _get_handler(self, acp_state, **session_kwargs):
        modules, acp, _ = acp_state
        session = make_session(**session_kwargs)
        with patch.dict(sys.modules, modules):
            await start_and_wait(session)
        return acp.AcpClient.last.connect_kwargs["permission_handler"], acp

    @pytest.mark.asyncio
    async def test_allowlisted_command_selects_allow_option(self):
        handler, acp = await self._get_handler(make_acp_module(), allowed_commands=["npm"])
        outcome = await handler(make_permission_request("npm test"))
        assert isinstance(outcome, acp.PermissionSelected) and outcome.option_id == "a1"

    @pytest.mark.asyncio
    async def test_unlisted_command_asks_user_and_approval_allows(self):
        on_request_command = AsyncMock(return_value="approved")
        handler, acp = await self._get_handler(
            make_acp_module(), allowed_commands=["npm"], on_request_command=on_request_command)
        outcome = await handler(make_permission_request("curl http://x"))
        assert isinstance(outcome, acp.PermissionSelected) and outcome.option_id == "a1"
        assert on_request_command.call_args.args[0] == "curl http://x"

    @pytest.mark.asyncio
    async def test_user_denial_selects_reject_option(self):
        on_request_command = AsyncMock(return_value="denied")
        handler, acp = await self._get_handler(
            make_acp_module(), on_request_command=on_request_command)
        outcome = await handler(make_permission_request())
        assert isinstance(outcome, acp.PermissionSelected) and outcome.option_id == "r1"

    @pytest.mark.asyncio
    async def test_no_callback_denies_unlisted_command(self):
        handler, acp = await self._get_handler(make_acp_module())
        outcome = await handler(make_permission_request())
        assert isinstance(outcome, acp.PermissionSelected) and outcome.option_id == "r1"

    @pytest.mark.asyncio
    async def test_non_execute_allowed_without_asking(self):
        on_request_command = AsyncMock()
        handler, acp = await self._get_handler(
            make_acp_module(), on_request_command=on_request_command)
        outcome = await handler(make_permission_request(kind="read", command=None))
        assert isinstance(outcome, acp.PermissionSelected) and outcome.option_id == "a1"
        on_request_command.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_matching_options_cancels(self):
        handler, acp = await self._get_handler(make_acp_module())
        outcome = await handler(make_permission_request(options=[]))
        assert isinstance(outcome, acp.PermissionCancelled)


class TestBoardTools:
    @pytest.mark.asyncio
    async def test_board_mcp_config_passed_when_base_url_set(self):
        modules, acp, _ = make_acp_module()
        session = make_session(item_id="item-9")
        with patch.dict(sys.modules, modules), \
             patch.dict(os.environ, {"DASHBOARD_BASE_URL": "http://127.0.0.1:8001"}):
            await start_and_wait(session)
        cfg = acp.AcpClient.last.new_session_kwargs["mcp_servers"][0]
        assert cfg["name"] == "board"
        assert cfg["args"][0].endswith("kimi_board_mcp.py")
        env = {e["name"]: e["value"] for e in cfg["env"]}
        assert env["DASHBOARD_BASE_URL"] == "http://127.0.0.1:8001"
        assert env["DASHBOARD_ITEM_ID"] == "item-9"
        assert "DASHBOARD_REPO" not in env

    @pytest.mark.asyncio
    async def test_repo_env_included_in_multi_repo_mode(self):
        modules, acp, _ = make_acp_module()
        session = make_session(item_id="item-9", item_repo_name="backend")
        with patch.dict(sys.modules, modules), \
             patch.dict(os.environ, {"DASHBOARD_BASE_URL": "http://127.0.0.1:8001"}):
            await start_and_wait(session)
        cfg = acp.AcpClient.last.new_session_kwargs["mcp_servers"][0]
        env = {e["name"]: e["value"] for e in cfg["env"]}
        assert env["DASHBOARD_REPO"] == "backend"

    @pytest.mark.asyncio
    async def test_no_board_mcp_without_base_url(self):
        modules, acp, _ = make_acp_module()
        session = make_session(item_id="item-9")
        with patch.dict(sys.modules, modules), patch.dict(os.environ):
            os.environ.pop("DASHBOARD_BASE_URL", None)
            await start_and_wait(session)
        assert acp.AcpClient.last.new_session_kwargs["mcp_servers"] is None

    @pytest.mark.asyncio
    async def test_no_board_mcp_without_item_id(self):
        modules, acp, _ = make_acp_module()
        session = make_session()  # item_id defaults to None
        with patch.dict(sys.modules, modules), \
             patch.dict(os.environ, {"DASHBOARD_BASE_URL": "http://127.0.0.1:8001"}):
            await start_and_wait(session)
        assert acp.AcpClient.last.new_session_kwargs["mcp_servers"] is None


class TestResume:
    @pytest.mark.asyncio
    async def test_resume_loads_existing_session(self):
        modules, acp, items = make_acp_module()
        session = make_session()
        with patch.dict(sys.modules, modules):
            await start_and_wait(session, resume_session_id="old-acp-session")
        client = acp.AcpClient.last
        assert client.load_session_calls == [("old-acp-session", Path("/tmp/test-worktree"))]
        assert client.new_session_calls == []
        assert session.current_session_id == "old-acp-session"

    @pytest.mark.asyncio
    async def test_resume_falls_back_to_new_session(self):
        modules, acp, items = make_acp_module(load_raises=RuntimeError("no loadSession capability"))
        session = make_session()
        with patch.dict(sys.modules, modules):
            await start_and_wait(session, resume_session_id="old-acp-session")
        client = acp.AcpClient.last
        assert len(client.load_session_calls) == 1
        assert client.new_session_calls == [Path("/tmp/test-worktree")]
        assert session.current_session_id == "acp-1"
