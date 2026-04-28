"""Add context column to clarifications table.

Stores optional contextual information alongside the agent's question
(e.g., relevant file paths, code snippets, prior decisions) so the user
has the necessary background to give a well-informed response.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class AddContextToClarificationsMigration(Migration):

    def __init__(self):
        super().__init__(
            version="021",
            description="Add context column to clarifications table"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        await db.execute("""
            ALTER TABLE clarifications
            ADD COLUMN context TEXT DEFAULT NULL
        """)

    async def down(self, db: aiosqlite.Connection) -> None:
        # SQLite 3.35+ supports DROP COLUMN; older versions require
        # full table recreation. For safety and to match the pattern
        # used by other column-add migrations in this project, leave
        # the column in place on rollback.
        pass
