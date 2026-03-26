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


class InitialSchemaMigration(Migration):
    """Creates the complete database schema."""

    def __init__(self):
        super().__init__(
            version="001",
            description="Initial database schema"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        """Create all tables."""

        # Items table - main kanban board items
        await db.execute("""
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
        """)

        # Work log table - agent activity stream
        await db.execute("""
            CREATE TABLE IF NOT EXISTS work_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id    TEXT NOT NULL REFERENCES items(id),
                timestamp  TEXT NOT NULL DEFAULT (datetime('now')),
                entry_type TEXT NOT NULL,
                content    TEXT NOT NULL,
                metadata   TEXT
            )
        """)

        # Review comments table - code review feedback
        await db.execute("""
            CREATE TABLE IF NOT EXISTS review_comments (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id     TEXT NOT NULL REFERENCES items(id),
                file_path   TEXT,
                line_number INTEGER,
                content     TEXT NOT NULL,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        # Clarifications table - agent questions awaiting user response
        await db.execute("""
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
        """)

        # Attachments table - uploaded files and images
        await db.execute("""
            CREATE TABLE IF NOT EXISTS attachments (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id     TEXT NOT NULL REFERENCES items(id),
                filename    TEXT NOT NULL,
                asset_path  TEXT NOT NULL,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        # Agent config table - system configuration (single row)
        await db.execute("""
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
        """)

        # Create default agent config row
        await db.execute(
            "INSERT OR IGNORE INTO agent_config (id) VALUES (1)"
        )

        # Token usage table - track token consumption per agent run
        await db.execute("""
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
        """)

        # Create indexes for efficient querying
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_token_usage_item_id ON token_usage(item_id)
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_token_usage_completed_at ON token_usage(completed_at)
        """)

    async def down(self, db: aiosqlite.Connection) -> None:
        """Drop all tables (destructive - use with caution)."""

        # Drop indexes
        await db.execute("DROP INDEX IF EXISTS idx_token_usage_completed_at")
        await db.execute("DROP INDEX IF EXISTS idx_token_usage_item_id")

        # Drop tables in reverse dependency order
        await db.execute("DROP TABLE IF EXISTS token_usage")
        await db.execute("DROP TABLE IF EXISTS attachments")
        await db.execute("DROP TABLE IF EXISTS clarifications")
        await db.execute("DROP TABLE IF EXISTS review_comments")
        await db.execute("DROP TABLE IF EXISTS work_log")
        await db.execute("DROP TABLE IF EXISTS agent_config")
        await db.execute("DROP TABLE IF EXISTS items")
