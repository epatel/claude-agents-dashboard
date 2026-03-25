"""Add MCP (Model Context Protocol) support to agent configuration.

This migration adds columns to support MCP servers configuration:
- mcp_servers: JSON array of configured MCP server configurations
- mcp_enabled: Boolean flag to enable/disable MCP functionality
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class AddMcpSupportMigration(Migration):
    """Adds MCP support columns to agent_config table."""

    def __init__(self):
        super().__init__(
            version="002",
            description="Add MCP support to agent configuration"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        """Add MCP columns to agent_config table."""

        # Add mcp_servers column (JSON array of MCP server configs)
        await db.execute("""
            ALTER TABLE agent_config
            ADD COLUMN mcp_servers TEXT DEFAULT '[]'
        """)

        # Add mcp_enabled column (boolean flag)
        await db.execute("""
            ALTER TABLE agent_config
            ADD COLUMN mcp_enabled INTEGER DEFAULT 0
        """)

    async def down(self, db: aiosqlite.Connection) -> None:
        """Remove MCP columns from agent_config table."""

        # Note: SQLite doesn't support DROP COLUMN directly
        # We need to recreate the table without MCP columns

        # Create new table without MCP columns
        await db.execute("""
            CREATE TABLE agent_config_backup (
                id              INTEGER PRIMARY KEY CHECK (id = 1),
                system_prompt   TEXT,
                tools           TEXT,
                model           TEXT DEFAULT 'claude-sonnet-4-20250514',
                project_context TEXT,
                updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        # Copy data (excluding MCP columns)
        await db.execute("""
            INSERT INTO agent_config_backup
            SELECT id, system_prompt, tools, model, project_context, updated_at
            FROM agent_config
        """)

        # Drop original table and rename backup
        await db.execute("DROP TABLE agent_config")
        await db.execute("ALTER TABLE agent_config_backup RENAME TO agent_config")