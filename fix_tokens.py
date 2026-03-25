#!/usr/bin/env python3
"""
Fix script to initialize token tracking database.
Run this to resolve the "Tokens still read 0" issue.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, 'src')

from src.database import Database


async def fix_tokens():
    """Initialize the database and run migrations to enable token tracking."""

    # Create agents-lab directory if it doesn't exist
    agents_lab_dir = Path("agents-lab")
    agents_lab_dir.mkdir(exist_ok=True)

    # Create database and run migrations
    db_path = agents_lab_dir / "dashboard.db"
    db = Database(db_path)

    print("🔧 Initializing database and running migrations...")

    try:
        await db.initialize()
        print("✅ Database initialized successfully!")

        # Check migration status
        status = await db.get_migration_status()
        print(f"📊 Database status:")
        print(f"   - Applied migrations: {status['applied_count']}")
        print(f"   - Latest applied: {status['latest_applied']}")

        if '005' in status['applied_migrations']:
            print("✅ Token usage table is ready!")
        else:
            print("❌ Token usage migration not found")

    except Exception as e:
        print(f"❌ Error: {e}")
        return False

    return True


if __name__ == "__main__":
    print("🚀 Fixing token tracking...")
    success = asyncio.run(fix_tokens())

    if success:
        print("\n✅ Fix complete! Next steps:")
        print("1. Start the dashboard with: ./run.sh")
        print("2. Run some agents to generate token usage")
        print("3. Check the token counter in the top navigation")
        print("\nThe tokens should now update properly as agents run.")
    else:
        print("\n❌ Fix failed. Check the error messages above.")
        sys.exit(1)