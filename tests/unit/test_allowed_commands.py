"""Tests for the allowed_commands migration (003)."""

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
