"""Add done_at column to items table.

Tracks when an item was moved to the 'done' column.
Backfills existing done items with their updated_at timestamp.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class AddDoneAtMigration(Migration):

    def __init__(self):
        super().__init__(
            version="007",
            description="Add done_at column to items"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        await db.execute("""
            ALTER TABLE items
            ADD COLUMN done_at TEXT DEFAULT NULL
        """)
        # Backfill existing done items with their updated_at timestamp
        await db.execute("""
            UPDATE items SET done_at = updated_at WHERE column_name = 'done' AND done_at IS NULL
        """)

    async def down(self, db: aiosqlite.Connection) -> None:
        pass
