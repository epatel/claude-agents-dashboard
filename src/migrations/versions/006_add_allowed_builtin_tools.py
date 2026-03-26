"""Add allowed_builtin_tools column to agent_config table.

Stores a JSON array of built-in tool names that agents are allowed to use
(e.g. WebSearch, WebFetch).
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class AddAllowedBuiltinToolsMigration(Migration):

    def __init__(self):
        super().__init__(
            version="006",
            description="Add allowed_builtin_tools column to agent_config"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        await db.execute("""
            ALTER TABLE agent_config
            ADD COLUMN allowed_builtin_tools TEXT DEFAULT '[]'
        """)

    async def down(self, db: aiosqlite.Connection) -> None:
        pass
