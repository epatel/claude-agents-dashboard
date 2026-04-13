"""Add WIP (work-in-progress) limit to agent_config.

Adds a wip_limit column that caps the number of concurrently running agents.
Items started beyond the limit are placed in 'doing' with status='queued'
and auto-started in position order when a slot opens.
0 means unlimited (default).
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class AddWipLimitMigration(Migration):

    def __init__(self):
        super().__init__(
            version="017",
            description="Add WIP limit to agent_config"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        await db.execute(
            "ALTER TABLE agent_config ADD COLUMN wip_limit INTEGER DEFAULT 0"
        )

    async def down(self, db: aiosqlite.Connection) -> None:
        await db.execute("""
            CREATE TABLE agent_config_backup AS SELECT
                id, system_prompt, tools, model, project_context,
                mcp_servers, mcp_enabled, plugins, allowed_commands,
                bash_yolo, allowed_builtin_tools, flame_enabled,
                flame_intensity_multiplier, ollama_enabled, ollama_base_url,
                created_at, updated_at
            FROM agent_config
        """)
        await db.execute("DROP TABLE agent_config")
        await db.execute("ALTER TABLE agent_config_backup RENAME TO agent_config")
