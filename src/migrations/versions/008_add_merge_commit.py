"""Add merge_commit column to items table.

Stores the git SHA of the merge commit when an item is approved.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class AddMergeCommitMigration(Migration):

    def __init__(self):
        super().__init__(
            version="008",
            description="Add merge_commit column to items"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        await db.execute("""
            ALTER TABLE items
            ADD COLUMN merge_commit TEXT DEFAULT NULL
        """)

    async def down(self, db: aiosqlite.Connection) -> None:
        await db.execute("""
            ALTER TABLE items
            DROP COLUMN merge_commit
        """)
