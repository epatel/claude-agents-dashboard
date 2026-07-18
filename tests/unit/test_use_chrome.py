"""Tests for the per-task Chrome browser integration (use_chrome).

When an item has use_chrome=True, its agent is launched with the `claude
--chrome` flag (via ClaudeAgentOptions.extra_args), the Claude-in-Chrome MCP
tools are allowed, and a browser-awareness note is appended to the system
prompt. Chrome is gated off in Ollama mode (small local models).
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent.session import ClaudeAgentSession
from src.models import ItemCreate, ItemUpdate
from src.services.session_service import SessionService
from src.services.workflow_service import WorkflowService

CHROME_TOOL_WILDCARD = "mcp__claude-in-chrome__*"


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestUseChromeModels:
    def test_item_create_defaults_off(self):
        assert ItemCreate(title="t").use_chrome is False

    def test_item_create_accepts_true(self):
        assert ItemCreate(title="t", use_chrome=True).use_chrome is True

    def test_item_update_unset_by_default(self):
        # Unset so PATCH doesn't clobber the stored value.
        assert "use_chrome" not in ItemUpdate(title="t").model_dump(exclude_unset=True)

    def test_item_update_accepts_value(self):
        dumped = ItemUpdate(use_chrome=True).model_dump(exclude_unset=True)
        assert dumped["use_chrome"] is True


# ---------------------------------------------------------------------------
# SessionService threads use_chrome through to ClaudeAgentSession
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSessionServiceThreadsUseChrome:
    async def test_defaults_false(self, temp_dir):
        session = await SessionService().create_session(
            item_id="t-1", worktree_path=temp_dir, config={},
            model="claude-sonnet-4-6",
        )
        assert session.use_chrome is False

    async def test_passes_true(self, temp_dir):
        session = await SessionService().create_session(
            item_id="t-2", worktree_path=temp_dir, config={},
            model="claude-sonnet-4-6", use_chrome=True,
        )
        assert session.use_chrome is True


# ---------------------------------------------------------------------------
# ClaudeAgentSession storage
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAgentSessionStoresUseChrome:
    def test_stored(self):
        session = ClaudeAgentSession(
            worktree_path=Path("/tmp/test"), system_prompt="x",
            model="claude-sonnet-4-6", use_chrome=True,
        )
        assert session.use_chrome is True

    def test_off_by_default(self):
        session = ClaudeAgentSession(
            worktree_path=Path("/tmp/test"), system_prompt="x",
            model="claude-sonnet-4-6",
        )
        assert session.use_chrome is False


# ---------------------------------------------------------------------------
# ClaudeAgentSession.start() — how use_chrome shapes ClaudeAgentOptions
# ---------------------------------------------------------------------------

async def _start_and_capture_options(mock_options_cls, mock_client_cls, **session_kwargs):
    mock_client_cls.return_value = AsyncMock()
    session = ClaudeAgentSession(
        system_prompt="base prompt",
        model="claude-sonnet-4-6",
        on_complete=AsyncMock(),
        **session_kwargs,
    )
    try:
        await session.start("Do something")
    except Exception:
        pass  # We only care how ClaudeAgentOptions was constructed.
    assert mock_options_cls.called, "ClaudeAgentOptions was never called"
    return mock_options_cls.call_args.kwargs


@pytest.mark.unit
class TestStartConfiguresChrome:
    @patch("src.agent.session.ClaudeSDKClient")
    @patch("src.agent.session.ClaudeAgentOptions")
    async def test_enabled_passes_chrome_extra_arg(self, mock_options, mock_client, temp_dir):
        kwargs = await _start_and_capture_options(
            mock_options, mock_client, worktree_path=temp_dir, use_chrome=True,
        )
        assert kwargs.get("extra_args") == {"chrome": None}

    @patch("src.agent.session.ClaudeSDKClient")
    @patch("src.agent.session.ClaudeAgentOptions")
    async def test_enabled_allows_chrome_tools(self, mock_options, mock_client, temp_dir):
        kwargs = await _start_and_capture_options(
            mock_options, mock_client, worktree_path=temp_dir, use_chrome=True,
        )
        assert CHROME_TOOL_WILDCARD in (kwargs.get("allowed_tools") or [])

    @patch("src.agent.session.ClaudeSDKClient")
    @patch("src.agent.session.ClaudeAgentOptions")
    async def test_enabled_notes_browser_in_prompt(self, mock_options, mock_client, temp_dir):
        kwargs = await _start_and_capture_options(
            mock_options, mock_client, worktree_path=temp_dir, use_chrome=True,
        )
        assert "claude-in-chrome" in (kwargs.get("system_prompt") or "")

    @patch("src.agent.session.ClaudeSDKClient")
    @patch("src.agent.session.ClaudeAgentOptions")
    async def test_disabled_no_chrome(self, mock_options, mock_client, temp_dir):
        kwargs = await _start_and_capture_options(
            mock_options, mock_client, worktree_path=temp_dir, use_chrome=False,
        )
        assert kwargs.get("extra_args") == {}
        assert CHROME_TOOL_WILDCARD not in (kwargs.get("allowed_tools") or [])
        assert "claude-in-chrome" not in (kwargs.get("system_prompt") or "")

    @patch("src.agent.session.ClaudeSDKClient")
    @patch("src.agent.session.ClaudeAgentOptions")
    async def test_ollama_mode_disables_chrome(self, mock_options, mock_client, temp_dir):
        """Even with use_chrome=True, Ollama mode must not enable browser tools."""
        kwargs = await _start_and_capture_options(
            mock_options, mock_client, worktree_path=temp_dir, use_chrome=True,
            ollama_env={"ANTHROPIC_BASE_URL": "http://localhost:11434"},
        )
        # Ollama options block carries no extra_args at all.
        assert kwargs.get("extra_args") is None
        assert CHROME_TOOL_WILDCARD not in (kwargs.get("allowed_tools") or [])


# ---------------------------------------------------------------------------
# WorkflowService._item_session_kwargs surfaces the item's use_chrome flag
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestItemSessionKwargs:
    async def _kwargs(self, item):
        # git with no `repos` attr => single-repo mode (no multi-repo kwargs).
        # _item_session_kwargs also builds the who_am_i callback, so the fake
        # needs that factory method. Items here carry no epic_id, so the epic
        # lookup is skipped and no `epics` attr is required.
        fake = SimpleNamespace(
            git=SimpleNamespace(),
            _create_on_who_am_i_callback=lambda item_id: None,
        )
        return await WorkflowService._item_session_kwargs(fake, item)

    async def test_true_when_flag_set(self):
        assert (await self._kwargs({"use_chrome": 1}))["use_chrome"] is True

    async def test_false_when_flag_zero(self):
        assert (await self._kwargs({"use_chrome": 0}))["use_chrome"] is False

    async def test_false_when_missing(self):
        assert (await self._kwargs({}))["use_chrome"] is False

    async def test_false_when_item_none(self):
        assert (await self._kwargs(None))["use_chrome"] is False
