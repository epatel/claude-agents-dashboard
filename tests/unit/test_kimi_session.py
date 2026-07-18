"""Unit tests for src/agent/kimi_session.py — KimiAgentSession (experimental)."""

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
    _tool_call_input,
    _tool_call_name,
)


class FakeToolCall:
    def __init__(self, name, arguments):
        self.id = "tc-1"
        self.type = "function"
        self.function = {"name": name, "arguments": arguments}


class FakeMessage:
    def __init__(self, role="assistant", text="", tool_calls=None):
        self.role = role
        self._text = text
        self.tool_calls = tool_calls

    def extract_text(self):
        return self._text


def make_session(**kwargs):
    defaults = dict(
        worktree_path=Path("/tmp/test-worktree"),
        system_prompt="You are a helpful agent.",
        model="kimi-k2",
    )
    defaults.update(kwargs)
    return KimiAgentSession(**defaults)


def install_fake_sdk(messages, raise_after=None):
    """Return a sys.modules patch dict providing kimi_agent_sdk + kaos.path."""

    async def fake_prompt(user_input, **kwargs):
        fake_prompt.calls.append((user_input, kwargs))
        for m in messages:
            yield m
        if raise_after is not None:
            raise raise_after

    fake_prompt.calls = []

    sdk = types.ModuleType("kimi_agent_sdk")
    sdk.prompt = fake_prompt
    kaos = types.ModuleType("kaos")
    kaos_path = types.ModuleType("kaos.path")
    kaos_path.KaosPath = lambda p: p
    kaos.path = kaos_path
    return {"kimi_agent_sdk": sdk, "kaos": kaos, "kaos.path": kaos_path}, fake_prompt


async def start_and_wait(session, prompt="do the task"):
    await session.start(prompt)
    await session._task


class TestContract:
    def test_implements_abstract_session(self):
        assert issubclass(KimiAgentSession, AbstractAgentSession)

    def test_initial_state(self):
        s = make_session()
        assert s.current_session_id is None
        assert s._task is None


class TestToolCallHelpers:
    def test_name_and_dict_arguments(self):
        tc = FakeToolCall("read_file", {"path": "a.py"})
        assert _tool_call_name(tc) == "read_file"
        assert _tool_call_input(tc) == {"path": "a.py"}

    def test_json_string_arguments_parsed(self):
        tc = FakeToolCall("bash", '{"command": "ls"}')
        assert _tool_call_input(tc) == {"command": "ls"}

    def test_invalid_json_arguments_wrapped_raw(self):
        tc = FakeToolCall("bash", "not-json{")
        assert _tool_call_input(tc) == {"raw": "not-json{"}

    def test_missing_function_defaults(self):
        tc = types.SimpleNamespace(id="x", type="function", function=None)
        assert _tool_call_name(tc) == "unknown"
        assert _tool_call_input(tc) == {}


class TestRun:
    @pytest.mark.asyncio
    async def test_streams_text_and_tool_calls_then_completes(self):
        on_message = AsyncMock()
        on_tool_use = AsyncMock()
        on_complete = AsyncMock()
        modules, fake_prompt = install_fake_sdk([
            FakeMessage(text="working on it"),
            FakeMessage(text="", tool_calls=[FakeToolCall("bash", '{"command": "ls"}')]),
            FakeMessage(role="tool", text="ls output"),
            FakeMessage(text="done"),
        ])
        session = make_session(
            on_message=on_message, on_tool_use=on_tool_use, on_complete=on_complete
        )
        with patch.dict(sys.modules, modules):
            await start_and_wait(session)

        assert [c.args[0] for c in on_message.call_args_list] == ["working on it", "done"]
        on_tool_use.assert_awaited_once_with("bash", {"command": "ls"})
        result = on_complete.call_args.args[0]
        assert isinstance(result, AgentResult) and result.success is True

    @pytest.mark.asyncio
    async def test_prompt_includes_system_prompt_and_worktree(self):
        modules, fake_prompt = install_fake_sdk([])
        session = make_session()
        with patch.dict(sys.modules, modules):
            await start_and_wait(session, "fix the bug")
        user_input, kwargs = fake_prompt.calls[0]
        assert "You are a helpful agent." in user_input
        assert "/tmp/test-worktree" in user_input
        assert "fix the bug" in user_input
        assert kwargs["model"] == "kimi-k2"
        assert kwargs["yolo"] is True

    @pytest.mark.asyncio
    async def test_missing_sdk_reports_install_hint(self):
        on_error = AsyncMock()
        on_complete = AsyncMock()
        session = make_session(on_error=on_error, on_complete=on_complete)
        with patch.dict(sys.modules, {"kimi_agent_sdk": None, "kaos": None, "kaos.path": None}):
            await start_and_wait(session)
        on_error.assert_awaited_once_with(KIMI_SDK_INSTALL_HINT)
        on_complete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sdk_error_reported_via_on_error(self):
        on_error = AsyncMock()
        on_complete = AsyncMock()
        modules, _ = install_fake_sdk(
            [FakeMessage(text="partial")], raise_after=RuntimeError("provider exploded")
        )
        session = make_session(on_error=on_error, on_complete=on_complete)
        with patch.dict(sys.modules, modules):
            await start_and_wait(session)
        on_error.assert_awaited_once_with("provider exploded")
        on_complete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cancel_stops_run_without_completion(self):
        on_complete = AsyncMock()

        async def slow_prompt(user_input, **kwargs):
            yield FakeMessage(text="starting")
            await asyncio.sleep(30)
            yield FakeMessage(text="never reached")

        sdk = types.ModuleType("kimi_agent_sdk")
        sdk.prompt = slow_prompt
        kaos = types.ModuleType("kaos")
        kaos_path = types.ModuleType("kaos.path")
        kaos_path.KaosPath = lambda p: p
        kaos.path = kaos_path

        session = make_session(on_complete=on_complete)
        with patch.dict(sys.modules, {"kimi_agent_sdk": sdk, "kaos": kaos, "kaos.path": kaos_path}):
            await session.start("task")
            await asyncio.sleep(0.05)
            await session.cancel()

        on_complete.assert_not_awaited()
        assert session._task.done()

    @pytest.mark.asyncio
    async def test_resume_session_id_ignored_starts_fresh(self):
        modules, fake_prompt = install_fake_sdk([])
        session = make_session()
        with patch.dict(sys.modules, modules):
            await session.start("task", resume_session_id="old-session")
            await session._task
        assert len(fake_prompt.calls) == 1
        assert session.current_session_id is None
