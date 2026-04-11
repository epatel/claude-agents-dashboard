"""Add start_copy flag to items.

When enabled, the Start button on the card becomes a Start Copy button,
keeping the original item in Todo when starting.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class AddStartCopyMigration(Migration):

    def __init__(self):
        super().__init__(
            version="014",
            description="Add start_copy flag to items"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        await db.execute(
            "ALTER TABLE items ADD COLUMN start_copy INTEGER DEFAULT 0"
        )

    async def down(self, db: aiosqlite.Connection) -> None:
        await db.execute("""
            CREATE TABLE items_backup AS SELECT
                id, title, description, column_name, position, status,
                branch_name, worktree_path, session_id, model,
                commit_message, created_at, updated_at, base_branch,
                base_commit, done_at, merge_commit, epic_id, auto_start
            FROM items
        """)
        await db.execute("DROP TABLE items")
        await db.execute("ALTER TABLE items_backup RENAME TO items")
