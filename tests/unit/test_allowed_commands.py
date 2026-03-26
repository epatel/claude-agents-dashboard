"""Tests for the allowed_commands migration (003)."""

import json

import pytest
import aiosqlite


class TestAllowedCommandsMigration:
    async def test_migration_adds_column(self, test_db):
        """Verify allowed_commands column exists with default value."""
        async with test_db.connect() as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT allowed_commands FROM agent_config")
            row = await cursor.fetchone()
            assert row["allowed_commands"] == "[]"


from src.agent.command_filter import make_command_filter_hook


class TestCommandFilterHook:
    async def test_allows_matching_command(self):
        hook = make_command_filter_hook(["flutter", "dart"])
        result = await hook(
            {"tool_name": "Bash", "tool_input": {"command": "flutter create myapp"}},
            "tool-123",
            {},
        )
        assert result == {}

    async def test_denies_unmatched_command(self):
        hook = make_command_filter_hook(["flutter"])
        result = await hook(
            {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}},
            "tool-123",
            {},
        )
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "request_command_access" in result["hookSpecificOutput"]["permissionDecisionReason"]

    async def test_allows_non_bash_tools(self):
        hook = make_command_filter_hook(["flutter"])
        result = await hook(
            {"tool_name": "Read", "tool_input": {"file_path": "/etc/passwd"}},
            "tool-123",
            {},
        )
        assert result == {}

    async def test_matches_first_word_only(self):
        hook = make_command_filter_hook(["flutter"])
        result = await hook(
            {"tool_name": "Bash", "tool_input": {"command": "flutter-evil steal"}},
            "tool-123",
            {},
        )
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"

    async def test_empty_allowed_list_denies_all_bash(self):
        hook = make_command_filter_hook([])
        result = await hook(
            {"tool_name": "Bash", "tool_input": {"command": "echo hello"}},
            "tool-123",
            {},
        )
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"


from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path

from src.agent.session import AgentSession


class TestAllowedToolsWhitelist:
    """Verify that allowed_tools is built correctly so Bash and plugins aren't blocked."""

    def _make_session(self, allowed_commands=None, bash_yolo=False, plugins=None):
        return AgentSession(
            worktree_path=Path("/tmp/fake-worktree"),
            system_prompt="test",
            allowed_commands=allowed_commands or [],
            bash_yolo=bash_yolo,
            plugins=plugins,
            on_clarify=AsyncMock(),
            on_create_todo=AsyncMock(),
            on_set_commit_message=AsyncMock(),
            on_request_command=AsyncMock(),
        )

    @patch("src.agent.session.ClaudeSDKClient")
    async def test_bash_in_whitelist_with_no_commands(self, mock_sdk):
        """Bash must be in allowed_tools even without allowed_commands or bash_yolo."""
        mock_client = AsyncMock()
        mock_sdk.return_value = mock_client

        session = self._make_session()
        # Capture the options passed to ClaudeSDKClient
        with patch.object(session, '_receive_loop', new_callable=AsyncMock):
            try:
                await session.start("test prompt")
            except Exception:
                pass

        args, kwargs = mock_sdk.call_args
        options = kwargs.get("options") or args[0]
        assert "Bash" in options.allowed_tools

    @patch("src.agent.session.ClaudeSDKClient")
    async def test_bash_in_whitelist_with_allowed_commands(self, mock_sdk):
        """Bash must be in allowed_tools when allowed_commands is set."""
        mock_client = AsyncMock()
        mock_sdk.return_value = mock_client

        session = self._make_session(allowed_commands=["flutter", "npm"])
        with patch.object(session, '_receive_loop', new_callable=AsyncMock):
            try:
                await session.start("test prompt")
            except Exception:
                pass

        options = mock_sdk.call_args.kwargs.get("options") or mock_sdk.call_args.args[0]
        assert "Bash" in options.allowed_tools

    @patch("src.agent.session.ClaudeSDKClient")
    async def test_bash_in_whitelist_with_bash_yolo(self, mock_sdk):
        """Bash must be in allowed_tools when bash_yolo is enabled."""
        mock_client = AsyncMock()
        mock_sdk.return_value = mock_client

        session = self._make_session(bash_yolo=True)
        with patch.object(session, '_receive_loop', new_callable=AsyncMock):
            try:
                await session.start("test prompt")
            except Exception:
                pass

        options = mock_sdk.call_args.kwargs.get("options") or mock_sdk.call_args.args[0]
        assert "Bash" in options.allowed_tools

    @patch("src.agent.session.ClaudeSDKClient")
    async def test_plugin_tools_in_whitelist(self, mock_sdk):
        """Plugin tools must get wildcard entries in allowed_tools."""
        mock_client = AsyncMock()
        mock_sdk.return_value = mock_client

        plugins = [{"type": "local", "path": "/home/user/.claude/plugins/context-mode"}]
        session = self._make_session(plugins=plugins)
        with patch.object(session, '_receive_loop', new_callable=AsyncMock):
            try:
                await session.start("test prompt")
            except Exception:
                pass

        options = mock_sdk.call_args.kwargs.get("options") or mock_sdk.call_args.args[0]
        assert "mcp__plugin_context-mode_*__*" in options.allowed_tools
        assert "mcp__plugin_context-mode_*" in options.allowed_tools

    @patch("src.agent.session.ClaudeSDKClient")
    async def test_hook_only_set_with_allowed_commands(self, mock_sdk):
        """PreToolUse hooks: tool filter hooks always present, Bash hook only with allowed_commands."""
        mock_client = AsyncMock()
        mock_sdk.return_value = mock_client

        # No commands, no yolo — tool filter hooks still present (for WebSearch/WebFetch)
        session = self._make_session()
        with patch.object(session, '_receive_loop', new_callable=AsyncMock):
            try:
                await session.start("test prompt")
            except Exception:
                pass
        options = mock_sdk.call_args.kwargs.get("options") or mock_sdk.call_args.args[0]
        assert options.hooks is not None
        assert "PreToolUse" in options.hooks
        matchers = options.hooks["PreToolUse"]
        bash_matchers = [m for m in matchers if m.matcher == "Bash"]
        assert len(bash_matchers) == 0  # No Bash hook without allowed_commands

        # With commands — Bash hook should also be set
        mock_sdk.reset_mock()
        session = self._make_session(allowed_commands=["flutter"])
        with patch.object(session, '_receive_loop', new_callable=AsyncMock):
            try:
                await session.start("test prompt")
            except Exception:
                pass
        options = mock_sdk.call_args.kwargs.get("options") or mock_sdk.call_args.args[0]
        assert options.hooks is not None
        assert "PreToolUse" in options.hooks
        matchers = options.hooks["PreToolUse"]
        bash_matchers = [m for m in matchers if m.matcher == "Bash"]
        assert len(bash_matchers) == 1


from src.agent.command_access import create_command_access_server


class TestCommandAccessMCPTool:
    async def test_creates_server(self):
        async def mock_callback(cmd, reason):
            return "approved"

        server = create_command_access_server(mock_callback)
        assert server is not None


class TestPermissionRequestFlow:
    async def test_approve_saves_command(self, test_db):
        """Approving a command request saves it to agent_config."""
        async with test_db.connect() as db:
            db.row_factory = aiosqlite.Row
            # Verify initial state
            cursor = await db.execute("SELECT allowed_commands FROM agent_config")
            row = await cursor.fetchone()
            commands = json.loads(row["allowed_commands"])
            assert commands == []

            # Simulate saving a command
            commands.append("flutter")
            await db.execute(
                "UPDATE agent_config SET allowed_commands = ?",
                [json.dumps(commands)],
            )
            await db.commit()

            # Verify
            cursor = await db.execute("SELECT allowed_commands FROM agent_config")
            row = await cursor.fetchone()
            assert json.loads(row["allowed_commands"]) == ["flutter"]

    async def test_multiple_commands(self, test_db):
        """Multiple commands can be saved."""
        async with test_db.connect() as db:
            db.row_factory = aiosqlite.Row
            commands = ["flutter", "dart", "npm"]
            await db.execute(
                "UPDATE agent_config SET allowed_commands = ?",
                [json.dumps(commands)],
            )
            await db.commit()

            cursor = await db.execute("SELECT allowed_commands FROM agent_config")
            row = await cursor.fetchone()
            assert json.loads(row["allowed_commands"]) == ["flutter", "dart", "npm"]
