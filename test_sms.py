#!/usr/bin/env python3
"""
Test SMS MCP Functionality

This script tests the SMS MCP configuration by making a direct API request
to verify the MCP server is accessible and working correctly.
"""

import asyncio
import aiohttp
import json
import sys
from datetime import datetime


async def test_sms_mcp_server():
    """Test the SMS MCP server directly."""
    url = "https://home.memention.net/sms_mcp/sse?api_key=YOUR_API_KEY_HERE"

    print("🧪 Testing SMS MCP Server")
    print(f"URL: {url}")
    print("=" * 60)

    try:
        async with aiohttp.ClientSession() as session:
            print("📡 Connecting to MCP server...")

            # Test basic connectivity
            async with session.get(url) as response:
                print(f"Status Code: {response.status}")
                print(f"Content Type: {response.content_type}")

                if response.status == 200:
                    print("✅ MCP server is accessible")

                    # Read initial data
                    content = await response.text()
                    print(f"Response preview: {content[:200]}...")

                    return True
                else:
                    print(f"❌ MCP server returned status {response.status}")
                    print(f"Response: {await response.text()}")
                    return False

    except aiohttp.ClientError as e:
        print(f"❌ Connection error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False


async def test_database_configuration():
    """Test that SMS MCP is properly configured in the database."""
    print("\n📁 Testing Database Configuration")
    print("=" * 60)

    import sqlite3
    from pathlib import Path

    db_path = Path("agents-lab/dashboard.db")
    if not db_path.exists():
        print("⚠️  Database not found - run configuration script first")
        return False

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Check agent configuration
        cursor.execute("SELECT mcp_enabled, mcp_servers FROM agent_config WHERE id = 1")
        row = cursor.fetchone()

        if row:
            mcp_enabled = bool(row['mcp_enabled'])
            mcp_servers = row['mcp_servers']

            print(f"✅ MCP Enabled: {mcp_enabled}")

            if mcp_enabled and mcp_servers:
                try:
                    servers = json.loads(mcp_servers)
                    print(f"✅ MCP Servers configured: {list(servers.keys())}")

                    sms_config = servers.get('sms')
                    if sms_config:
                        print(f"✅ SMS Server Type: {sms_config.get('type')}")
                        print(f"✅ SMS Server URL configured")
                        conn.close()
                        return True
                    else:
                        print("❌ SMS server not found in configuration")
                        conn.close()
                        return False
                except json.JSONDecodeError:
                    print("❌ Invalid JSON in mcp_servers field")
                    conn.close()
                    return False
            else:
                print("❌ MCP not enabled or no servers configured")
                conn.close()
                return False
        else:
            print("❌ No agent configuration found")
            conn.close()
            return False

    except Exception as e:
        print(f"❌ Database error: {e}")
        return False




async def main():
    """Run all tests."""
    print("🚀 SMS MCP Integration Test Suite")
    print(f"Started at: {datetime.now().isoformat()}")
    print("=" * 60)

    results = []

    # Test database configuration
    config_ok = await test_database_configuration()
    results.append(("Database Configuration", config_ok))

    # Test MCP server connectivity
    server_ok = await test_sms_mcp_server()
    results.append(("MCP Server", server_ok))

    # Summary
    print("\n" + "=" * 60)
    print("📊 Test Results Summary")
    print("=" * 60)

    for test_name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{test_name:.<20} {status}")

    all_passed = all(result[1] for result in results)

    if all_passed:
        print("\n🎉 All tests passed! SMS MCP integration is ready.")
        print("\nNext steps:")
        print("1. Start the dashboard: python -m src.main")
        print("2. Create a test task to send SMS to 0708554888")
        print("3. Verify SMS delivery")
    else:
        print("\n⚠️  Some tests failed. Please review the setup.")
        print("Refer to SMS_MCP_SETUP.md for configuration instructions.")

    return 0 if all_passed else 1


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\n\n⏹️  Test cancelled by user")
        sys.exit(1)