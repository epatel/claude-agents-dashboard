"""Add pause_message column to items.

Stores an optional comment supplied by the user when pausing an agent,
e.g. "investigate a different approach using async/await". The message
is prepended to the resume prompt and cleared once the agent resumes.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class AddPauseMessageMigration(Migration):

    def __init__(self):
        super().__init__(
            version="023",
            description="Add pause_message column to items"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        await db.execute(
            "ALTER TABLE items ADD COLUMN pause_message TEXT"
        )

    async def down(self, db: aiosqlite.Connection) -> None:
        # Match the no-op pattern used by other column-add migrations.
        pass
