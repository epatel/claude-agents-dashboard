"""Add token usage tracking table.

This migration adds a token_usage table to track token consumption per agent run,
enabling detailed analytics on token usage alongside cost tracking.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class AddTokenUsageMigration(Migration):
    """Adds token_usage table for tracking token consumption per agent run."""

    def __init__(self):
        super().__init__(
            version="005",
            description="Add token usage tracking table"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        """Create token_usage table."""
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

        # Create index for efficient querying
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_token_usage_item_id ON token_usage(item_id)
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_token_usage_completed_at ON token_usage(completed_at)
        """)

    async def down(self, db: aiosqlite.Connection) -> None:
        """Drop token_usage table."""
        await db.execute("DROP INDEX IF EXISTS idx_token_usage_completed_at")
        await db.execute("DROP INDEX IF EXISTS idx_token_usage_item_id")
        await db.execute("DROP TABLE IF EXISTS token_usage")