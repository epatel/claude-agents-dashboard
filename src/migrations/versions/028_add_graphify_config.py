"""Add graphify config to agent_config.

Backs the Settings ▸ Graphify tab:
- graphify_enabled: expose the read-only graph_query MCP tool to agents.
- graphify_auto_refresh: re-run the (free) AST graph build after a merge.
- graphify_backend: default extraction depth — 'ast' (free) or 'gemini' (semantic).
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class AddGraphifyConfigMigration(Migration):

    def __init__(self):
        super().__init__(
            version="028",
            description="Add graphify config to agent_config"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        await db.execute(
            "ALTER TABLE agent_config ADD COLUMN graphify_enabled INTEGER DEFAULT 0"
        )
        await db.execute(
            "ALTER TABLE agent_config ADD COLUMN graphify_auto_refresh INTEGER DEFAULT 1"
        )
        await db.execute(
            "ALTER TABLE agent_config ADD COLUMN graphify_backend TEXT DEFAULT 'ast'"
        )

    async def down(self, db: aiosqlite.Connection) -> None:
        # SQLite column-add migrations leave the columns on rollback — match
        # the no-op pattern used by the other recent column-add migrations (022).
        pass
