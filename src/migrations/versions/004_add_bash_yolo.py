"""Add bash_yolo column to agent_config table."""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class AddBashYolo(Migration):

    def __init__(self):
        super().__init__(
            version="004",
            description="Add bash_yolo to agent_config"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        await db.execute(
            "ALTER TABLE agent_config ADD COLUMN bash_yolo BOOLEAN DEFAULT 0"
        )

    async def down(self, db: aiosqlite.Connection) -> None:
        # SQLite < 3.35 doesn't support DROP COLUMN; acceptable to leave column
        pass
