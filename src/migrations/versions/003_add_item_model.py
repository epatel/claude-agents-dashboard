"""Add model selection support to individual items.

This migration adds a model column to the items table to support per-issue model selection:
- model: The AI model to use for this specific item (defaults to None for fallback to global config)
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class AddItemModelMigration(Migration):
    """Adds model column to items table for per-issue model selection."""

    def __init__(self):
        super().__init__(
            version="003",
            description="Add model selection support to individual items"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        """Add model column to items table."""

        # Add model column (optional, defaults to None to use global config)
        await db.execute("""
            ALTER TABLE items
            ADD COLUMN model TEXT DEFAULT NULL
        """)

    async def down(self, db: aiosqlite.Connection) -> None:
        """Remove model column from items table."""

        # Note: SQLite doesn't support DROP COLUMN directly
        # We need to recreate the table without the model column

        # Create new table without model column
        await db.execute("""
            CREATE TABLE items_backup (
                id            TEXT PRIMARY KEY,
                title         TEXT NOT NULL,
                description   TEXT NOT NULL DEFAULT '',
                column_name   TEXT NOT NULL DEFAULT 'todo',
                position      INTEGER NOT NULL DEFAULT 0,
                status        TEXT DEFAULT NULL,
                branch_name   TEXT DEFAULT NULL,
                worktree_path TEXT DEFAULT NULL,
                session_id    TEXT DEFAULT NULL,
                created_at    TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        # Copy data (excluding model column)
        await db.execute("""
            INSERT INTO items_backup
            SELECT id, title, description, column_name, position, status, branch_name, worktree_path, session_id, created_at, updated_at
            FROM items
        """)

        # Drop original table and rename backup
        await db.execute("DROP TABLE items")
        await db.execute("ALTER TABLE items_backup RENAME TO items")