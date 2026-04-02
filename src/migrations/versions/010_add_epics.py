"""Add epics table and epic_id column to items.

Epics group board items into higher-level work streams.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class AddEpicsMigration(Migration):

    def __init__(self):
        super().__init__(
            version="010",
            description="Add epics table and epic_id to items"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS epics (
                id         TEXT PRIMARY KEY,
                title      TEXT NOT NULL,
                color      TEXT NOT NULL DEFAULT 'blue',
                position   INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            ALTER TABLE items
            ADD COLUMN epic_id TEXT DEFAULT NULL REFERENCES epics(id)
        """)

    async def down(self, db: aiosqlite.Connection) -> None:
        await db.execute("ALTER TABLE items DROP COLUMN epic_id")
        await db.execute("DROP TABLE IF EXISTS epics")
