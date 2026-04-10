"""Add flame animation settings to agent_config.

Adds flame_enabled and flame_intensity_multiplier columns
for the background flame animation feature.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class AddFlameSettingsMigration(Migration):

    def __init__(self):
        super().__init__(
            version="013",
            description="Add flame animation settings to agent_config"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        await db.execute(
            "ALTER TABLE agent_config ADD COLUMN flame_enabled INTEGER DEFAULT 1"
        )
        await db.execute(
            "ALTER TABLE agent_config ADD COLUMN flame_intensity_multiplier REAL DEFAULT 1.0"
        )

    async def down(self, db: aiosqlite.Connection) -> None:
        # SQLite doesn't support DROP COLUMN before 3.35
        # Rebuild the table without the new columns
        await db.execute("""
            CREATE TABLE agent_config_backup AS SELECT
                id, system_prompt, tools, model, project_context,
                mcp_servers, mcp_enabled, plugins, allowed_commands,
                bash_yolo, allowed_builtin_tools, updated_at
            FROM agent_config
        """)
        await db.execute("DROP TABLE agent_config")
        await db.execute("ALTER TABLE agent_config_backup RENAME TO agent_config")
