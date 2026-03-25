"""Add plugin support to agent configuration.

This migration adds a plugins column to the agent_config table to store
local plugin directory paths that are loaded into agent sessions via the
Claude Agent SDK's plugin system.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class AddPluginsMigration(Migration):
    """Adds plugins column to agent_config for plugin directory paths."""

    def __init__(self):
        super().__init__(
            version="006",
            description="Add plugin support to agent configuration"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        """Add plugins column to agent_config table."""
        await db.execute("""
            ALTER TABLE agent_config ADD COLUMN plugins TEXT DEFAULT '[]'
        """)

    async def down(self, db: aiosqlite.Connection) -> None:
        """Remove plugins column (SQLite doesn't support DROP COLUMN easily)."""
        # SQLite 3.35.0+ supports DROP COLUMN
        await db.execute("""
            ALTER TABLE agent_config DROP COLUMN plugins
        """)
