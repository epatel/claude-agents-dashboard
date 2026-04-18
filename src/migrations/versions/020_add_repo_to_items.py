"""Add repo column to items for multi-repo workspace support.

In multi-repo mode the dashboard targets a parent folder containing several
sibling git repos; each item picks one of those repos. Column is nullable so
existing single-repo databases continue to work (NULL = the one target repo).
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class AddRepoToItemsMigration(Migration):

    def __init__(self):
        super().__init__(
            version="020",
            description="Add repo column to items for multi-repo workspace support"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        await db.execute("ALTER TABLE items ADD COLUMN repo TEXT")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_items_repo ON items(repo)")

    async def down(self, db: aiosqlite.Connection) -> None:
        await db.execute("DROP INDEX IF EXISTS idx_items_repo")
        # SQLite DROP COLUMN requires 3.35+; assume available (modern Python ships 3.37+).
        await db.execute("ALTER TABLE items DROP COLUMN repo")
