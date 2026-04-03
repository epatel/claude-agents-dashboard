"""Add item_dependencies join table.

Tracks dependencies between board items (item A requires item B).
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class AddItemDependenciesMigration(Migration):

    def __init__(self):
        super().__init__(
            version="011",
            description="Add item_dependencies table"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS item_dependencies (
                item_id          TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                requires_item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                PRIMARY KEY (item_id, requires_item_id)
            )
        """)

    async def down(self, db: aiosqlite.Connection) -> None:
        await db.execute("DROP TABLE IF EXISTS item_dependencies")
