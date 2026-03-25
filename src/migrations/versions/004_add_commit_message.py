"""Add commit_message column to items table.

This migration adds a commit_message column so agents can suggest a meaningful
commit message when they finish work, replacing the generic "Agent work on agent/nnn".
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class AddCommitMessageMigration(Migration):
    """Adds commit_message column to items table."""

    def __init__(self):
        super().__init__(
            version="004",
            description="Add commit_message column to items table"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        """Add commit_message column to items table."""
        await db.execute("""
            ALTER TABLE items
            ADD COLUMN commit_message TEXT DEFAULT NULL
        """)

    async def down(self, db: aiosqlite.Connection) -> None:
        """Remove commit_message column - SQLite doesn't support DROP COLUMN directly."""
        # Create new table without commit_message column
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
                model         TEXT DEFAULT NULL,
                created_at    TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        await db.execute("""
            INSERT INTO items_backup
            SELECT id, title, description, column_name, position, status, branch_name, worktree_path, session_id, model, created_at, updated_at
            FROM items
        """)

        await db.execute("DROP TABLE items")
        await db.execute("ALTER TABLE items_backup RENAME TO items")
