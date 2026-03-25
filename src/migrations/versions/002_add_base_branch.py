"""Add base_branch column to items table.

Stores which branch the worktree was created from, so merges go back
to the correct branch instead of always targeting main.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class AddBaseBranchMigration(Migration):

    def __init__(self):
        super().__init__(
            version="002",
            description="Add base_branch column to items table"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        await db.execute("""
            ALTER TABLE items
            ADD COLUMN base_branch TEXT DEFAULT NULL
        """)

    async def down(self, db: aiosqlite.Connection) -> None:
        # SQLite doesn't support DROP COLUMN in older versions,
        # but 3.35+ does. For safety, just leave the column.
        pass
