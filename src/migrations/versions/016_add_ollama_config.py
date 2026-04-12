"""Add Ollama provider config to agent_config.

Adds ollama_enabled flag and ollama_base_url to support running agents
against a local Ollama instance via Claude Code's env override mechanism.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class AddOllamaConfigMigration(Migration):

    def __init__(self):
        super().__init__(
            version="016",
            description="Add Ollama provider config to agent_config"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        await db.execute(
            "ALTER TABLE agent_config ADD COLUMN ollama_enabled INTEGER DEFAULT 0"
        )
        await db.execute(
            "ALTER TABLE agent_config ADD COLUMN ollama_base_url TEXT DEFAULT 'http://localhost:11434'"
        )

    async def down(self, db: aiosqlite.Connection) -> None:
        await db.execute("""
            CREATE TABLE agent_config_backup AS SELECT
                id, system_prompt, tools, model, project_context,
                mcp_servers, mcp_enabled, plugins, allowed_commands,
                bash_yolo, allowed_builtin_tools, flame_enabled,
                flame_intensity_multiplier, created_at, updated_at
            FROM agent_config
        """)
        await db.execute("DROP TABLE agent_config")
        await db.execute("ALTER TABLE agent_config_backup RENAME TO agent_config")
