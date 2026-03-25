#!/usr/bin/env python3
"""
Configure SMS MCP using proper options parameter format

This script configures SMS MCP integration using the correct approach:
- Uses options.mcpServers parameter
- Configures allowedTools for SMS
- No external config files
"""

import asyncio
import json
import sys
from pathlib import Path

# Add src to path for imports
sys.path.append(str(Path(__file__).parent / "src"))

from database import Database
from config import DEFAULT_AGENT_CONFIG


async def configure_sms_mcp():
    """Configure SMS MCP using the proper options parameter format."""

    # Initialize database
    db_path = Path("agents-lab/dashboard.db")
    db_path.parent.mkdir(exist_ok=True)

    db = Database(db_path)
    print("Initializing database...")
    await db.initialize()

    # Proper MCP configuration using options.mcpServers format
    # IMPORTANT: Replace YOUR_API_KEY_HERE with your actual API key
    mcp_servers_config = {
        "sms": {
            "type": "sse",
            "url": "https://home.memention.net/sms_mcp/sse?api_key=YOUR_API_KEY_HERE"
        }
    }

    # Prepare agent configuration
    config = DEFAULT_AGENT_CONFIG.copy()
    config.update({
        "system_prompt": "You are a helpful AI assistant with SMS capabilities. Use the SMS tools when asked to send messages.",
        "mcp_servers": json.dumps(mcp_servers_config),  # Store as JSON string
        "mcp_enabled": True,
    })

    print("Configuring SMS MCP with proper options parameter format...")
    print(f"MCP Servers: {mcp_servers_config}")

    async with db.connect() as conn:
        # Check if agent_config already exists
        cursor = await conn.execute("SELECT * FROM agent_config WHERE id = 1")
        existing_config = await cursor.fetchone()

        if existing_config:
            # Update existing configuration
            await conn.execute("""
                UPDATE agent_config
                SET system_prompt = ?, tools = ?, model = ?, project_context = ?,
                    mcp_servers = ?, mcp_enabled = ?, updated_at = datetime('now')
                WHERE id = 1
            """, (
                config["system_prompt"],
                json.dumps(config["tools"]),
                config["model"],
                config["project_context"],
                config["mcp_servers"],
                config["mcp_enabled"]
            ))
            print("Updated existing agent configuration")
        else:
            # Insert new configuration
            await conn.execute("""
                INSERT INTO agent_config
                (id, system_prompt, tools, model, project_context, mcp_servers, mcp_enabled, updated_at)
                VALUES (1, ?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                config["system_prompt"],
                json.dumps(config["tools"]),
                config["model"],
                config["project_context"],
                config["mcp_servers"],
                config["mcp_enabled"]
            ))
            print("Created new agent configuration")

        await conn.commit()

        # Verify configuration
        cursor = await conn.execute("SELECT * FROM agent_config WHERE id = 1")
        final_config = dict(await cursor.fetchone())

    print("\n✅ SMS MCP Configuration Complete!")
    print(f"MCP Enabled: {final_config['mcp_enabled']}")
    print(f"MCP Servers: {final_config['mcp_servers']}")

    # Parse and display the configuration
    try:
        servers = json.loads(final_config['mcp_servers'])
        for server_name, server_config in servers.items():
            print(f"  {server_name}: {server_config['type']} - {server_config['url']}")
    except:
        pass

    return final_config


async def create_test_task():
    """Create a test SMS task."""
    from models import new_id

    db_path = Path("agents-lab/dashboard.db")
    db = Database(db_path)

    async with db.connect() as conn:
        # Get next position in todo column
        cursor = await conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM items WHERE column_name = 'todo'"
        )
        row = await cursor.fetchone()
        position = row[0] if row else 0

        # Create test SMS item
        item_id = new_id()
        await conn.execute("""
            INSERT INTO items (id, title, description, column_name, position)
            VALUES (?, ?, ?, 'todo', ?)
        """, (
            item_id,
            "Test SMS via MCP",
            "Send an SMS to 0708554888 with the message: 'Hello! This is a test message from Claude via MCP using the proper options.mcpServers configuration!'",
            position
        ))
        await conn.commit()

    print(f"✅ Test SMS task created with ID: {item_id}")
    return item_id


async def main():
    """Main configuration function."""
    print("🚀 Configuring SMS MCP with proper options parameter")
    print("=" * 60)

    try:
        # Configure MCP
        config = await configure_sms_mcp()

        # Create test task
        test_item_id = await create_test_task()

        print("\n" + "=" * 60)
        print("🎉 Configuration Complete!")
        print("\nConfiguration Details:")
        print("✅ Using options.mcpServers parameter (not external files)")
        print("✅ SMS server configured for SSE endpoint")
        print("✅ Tools will be available as mcp__sms__*")
        print("\nNext Steps:")
        print("1. Start dashboard: python -m src.main")
        print("2. Open web interface (default: http://127.0.0.1:8000)")
        print(f"3. Run test task (ID: {test_item_id})")
        print("4. Verify SMS sent to 0708554888")

    except Exception as e:
        print(f"\n❌ Error during configuration: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))