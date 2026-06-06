"""Add enabled_skills to agent_config.

Per-project list of installed library skills delivered to agents (via the
SDK plugins= option). The DB lives in <target>/agents-lab, so this list is
naturally scoped per project. JSON-encoded list of skill names.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class AddEnabledSkillsMigration(Migration):

    def __init__(self):
        super().__init__(
            version="029",
            description="Add enabled_skills to agent_config"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        await db.execute(
            "ALTER TABLE agent_config ADD COLUMN enabled_skills TEXT DEFAULT '[]'"
        )

    async def down(self, db: aiosqlite.Connection) -> None:
        # Column-add migrations leave the column on rollback (matches 022/028).
        pass
