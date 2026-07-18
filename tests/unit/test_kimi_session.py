"""Unit tests for src/agent/kimi_session.py — KimiAgentSession over ACP (experimental)."""

import asyncio
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

    class FakeAcpSession:
        def __init__(self):
            self.id = session_id
            self.prompts = []
            self.cancelled = False

        async def prompt(self, user_input):
            self.prompts.append(user_input)
            for item in items:
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
            return self.session

        async def load_session(self, sid, cwd=None, **kwargs):
            self.load_session_calls.append((sid, cwd))
            if load_raises is not None:
                raise load_raises
            self.session.id = sid
            return self.session

    for cls in (TextContent, AgentMessageChunk, AgentThoughtChunk,
                ToolCallStart, ToolCallProgress, TurnEnded, AcpClient):
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
        assert client.connect_kwargs["yolo"] is True
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
