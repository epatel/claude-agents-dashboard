"""Initial database schema migration.

This migration creates the complete schema for the Agents Dashboard:
- items: Main kanban board items
- work_log: Agent activity logging
- review_comments: Code review feedback
- clarifications: Agent question prompts awaiting user response
- attachments: Uploaded files and images
- agent_config: System configuration (with MCP and plugin support)
- token_usage: Token consumption tracking per agent run
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


# Items table - main kanban board items
_ITEMS = """
            CREATE TABLE IF NOT EXISTS items (
                id            TEXT PRIMARY KEY,
                title         TEXT NOT NULL,
                description   TEXT NOT NULL DEFAULT '',
                column_name   TEXT NOT NULL DEFAULT 'todo',
                position      INTEGER NOT NULL DEFAULT 0,
                status        TEXT DEFAULT NULL,
                branch_name   TEXT DEFAULT NULL,
                worktree_path TEXT DEFAULT NULL,
                session_id    TEXT DEFAULT NULL,
                model         TEXT DEFAULT NULL,
                commit_message TEXT DEFAULT NULL,
                created_at    TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """

# Work log table - agent activity stream
_WORK_LOG = """
            CREATE TABLE IF NOT EXISTS work_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id    TEXT NOT NULL REFERENCES items(id),
                timestamp  TEXT NOT NULL DEFAULT (datetime('now')),
                entry_type TEXT NOT NULL,
                content    TEXT NOT NULL,
                metadata   TEXT
            )
        """

# Review comments table - code review feedback
_REVIEW_COMMENTS = """
            CREATE TABLE IF NOT EXISTS review_comments (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id     TEXT NOT NULL REFERENCES items(id),
                file_path   TEXT,
                line_number INTEGER,
                content     TEXT NOT NULL,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """

# Clarifications table - agent questions awaiting user response
_CLARIFICATIONS = """
            CREATE TABLE IF NOT EXISTS clarifications (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id     TEXT NOT NULL REFERENCES items(id),
                prompt      TEXT NOT NULL,
                choices     TEXT,
                allow_text  INTEGER NOT NULL DEFAULT 1,
                response    TEXT,
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                answered_at TEXT
            )
        """

# Attachments table - uploaded files and images
_ATTACHMENTS = """
            CREATE TABLE IF NOT EXISTS attachments (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id     TEXT NOT NULL REFERENCES items(id),
                filename    TEXT NOT NULL,
                asset_path  TEXT NOT NULL,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """

# Agent config table - system configuration (single row)
_AGENT_CONFIG = """
            CREATE TABLE IF NOT EXISTS agent_config (
                id              INTEGER PRIMARY KEY CHECK (id = 1),
                system_prompt   TEXT,
                tools           TEXT,
                model           TEXT DEFAULT 'claude-sonnet-4-20250514',
                project_context TEXT,
                mcp_servers     TEXT DEFAULT '{}',
                mcp_enabled     INTEGER DEFAULT 0,
                plugins         TEXT DEFAULT '[]',
                updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """

# Create default agent config row
_DEFAULT_AGENT_CONFIG_ROW = "INSERT OR IGNORE INTO agent_config (id) VALUES (1)"

# Token usage table - track token consumption per agent run
_TOKEN_USAGE = """
            CREATE TABLE IF NOT EXISTS token_usage (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id         TEXT NOT NULL REFERENCES items(id),
                session_id      TEXT,
                input_tokens    INTEGER,
                output_tokens   INTEGER,
                total_tokens    INTEGER,
                cost_usd        REAL,
                completed_at    TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """

# Index for efficient querying by item
_IDX_TOKEN_USAGE_ITEM_ID = """
            CREATE INDEX IF NOT EXISTS idx_token_usage_item_id ON token_usage(item_id)
        """

# Index for efficient querying by completion time
_IDX_TOKEN_USAGE_COMPLETED_AT = """
            CREATE INDEX IF NOT EXISTS idx_token_usage_completed_at ON token_usage(completed_at)
        """

# Every CREATE / INSERT statement, in the order up() runs them.
_UP_STATEMENTS = (
    _ITEMS,
    _WORK_LOG,
    _REVIEW_COMMENTS,
    _CLARIFICATIONS,
    _ATTACHMENTS,
    _AGENT_CONFIG,
    _DEFAULT_AGENT_CONFIG_ROW,
    _TOKEN_USAGE,
    _IDX_TOKEN_USAGE_ITEM_ID,
    _IDX_TOKEN_USAGE_COMPLETED_AT,
)

# What down() drops: indexes first, then tables in reverse dependency order.
_DROPPED = (
    ("INDEX", "idx_token_usage_completed_at"),
    ("INDEX", "idx_token_usage_item_id"),
    ("TABLE", "token_usage"),
    ("TABLE", "attachments"),
    ("TABLE", "clarifications"),
    ("TABLE", "review_comments"),
    ("TABLE", "work_log"),
    ("TABLE", "agent_config"),
    ("TABLE", "items"),
)


class InitialSchemaMigration(Migration):
    """Creates the complete database schema."""

    def __init__(self):
        super().__init__(
            version="001",
            description="Initial database schema"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        """Create all tables."""
        for statement in _UP_STATEMENTS:
            await db.execute(statement)

    async def down(self, db: aiosqlite.Connection) -> None:
        """Drop all tables (destructive - use with caution)."""
        for kind, name in _DROPPED:
            await db.execute(f"DROP {kind} IF EXISTS {name}")
