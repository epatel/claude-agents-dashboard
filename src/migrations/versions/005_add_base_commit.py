"""Add base_commit column to items table.

Stores the commit SHA of the base branch at worktree creation time,
so diffs are computed against a fixed point in history rather than
a moving branch reference.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class AddBaseCommitMigration(Migration):

    def __init__(self):
        super().__init__(
            version="005",
            description="Add base_commit column to items table"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        await db.execute("""
            ALTER TABLE items
            ADD COLUMN base_commit TEXT DEFAULT NULL
        """)

    async def down(self, db: aiosqlite.Connection) -> None:
        pass
