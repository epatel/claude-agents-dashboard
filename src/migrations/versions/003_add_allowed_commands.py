"""Add allowed_commands column to agent_config table.

Stores a JSON array of allowed shell commands that agents can execute.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class AddAllowedCommands(Migration):

    def __init__(self):
        super().__init__(
            version="003",
            description="Add allowed_commands to agent_config"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        await db.execute(
            "ALTER TABLE agent_config ADD COLUMN allowed_commands TEXT DEFAULT '[]'"
        )
        await db.execute(
            "ALTER TABLE agent_config ADD COLUMN bash_yolo BOOLEAN DEFAULT 0"
        )

    async def down(self, db: aiosqlite.Connection) -> None:
        await db.execute("""
            CREATE TABLE agent_config_backup AS
            SELECT id, system_prompt, model, project_context, mcp_servers,
                   mcp_enabled, plugins, updated_at
            FROM agent_config
        """)
        await db.execute("DROP TABLE agent_config")
        await db.execute("ALTER TABLE agent_config_backup RENAME TO agent_config")
