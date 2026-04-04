"""Add auto_start column to items.

When enabled, blocked items automatically start an agent when all
their dependencies are resolved.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class AddAutoStartMigration(Migration):

    def __init__(self):
        super().__init__(
            version="012",
            description="Add auto_start column to items"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        await db.execute(
            "ALTER TABLE items ADD COLUMN auto_start INTEGER DEFAULT 0"
        )

    async def down(self, db: aiosqlite.Connection) -> None:
        await db.execute("""
            CREATE TABLE items_backup AS SELECT
                id, title, description, column_name, position, status,
                branch_name, worktree_path, session_id, model,
                commit_message, created_at, updated_at, base_branch,
                base_commit, done_at, merge_commit, epic_id
            FROM items
        """)
        await db.execute("DROP TABLE items")
        await db.execute("ALTER TABLE items_backup RENAME TO items")
