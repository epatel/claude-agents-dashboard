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
