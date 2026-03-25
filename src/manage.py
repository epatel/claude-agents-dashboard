#!/usr/bin/env python3
"""Database management CLI for Agents Dashboard."""

import asyncio
import argparse
import sys
import logging
from pathlib import Path
from .database import Database

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="Manage Agents Dashboard database")
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path.cwd() / "agents-lab" / "dashboard.db",
        help="Path to SQLite database file (default: ./agents-lab/dashboard.db)"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Migration status command
    status_parser = subparsers.add_parser(
        "status",
        help="Show migration status"
    )

    # Migration up command
    migrate_parser = subparsers.add_parser(
        "migrate",
        help="Run pending migrations"
    )
    migrate_parser.add_argument(
        "--to",
        dest="target_version",
        help="Migrate to specific version (default: latest)"
    )

    # Migration down command
    rollback_parser = subparsers.add_parser(
        "rollback",
        help="Rollback migrations to specific version"
    )
    rollback_parser.add_argument(
        "target_version",
        help="Target version to rollback to"
    )

    # Initialize command
    init_parser = subparsers.add_parser(
        "init",
        help="Initialize database (same as migrate)"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Ensure db directory exists
    args.db_path.parent.mkdir(parents=True, exist_ok=True)

    # Initialize database
    db = Database(args.db_path)

    try:
        if args.command == "status":
            await show_migration_status(db)
        elif args.command == "migrate":
            await run_migrations(db, args.target_version)
        elif args.command == "rollback":
            await rollback_migrations(db, args.target_version)
        elif args.command == "init":
            await run_migrations(db, None)
        else:
            parser.print_help()

    except Exception as e:
        logger.error(f"Command failed: {e}")
        sys.exit(1)


async def show_migration_status(db: Database):
    """Show current migration status."""
    print("Database Migration Status")
    print("=" * 40)

    if not db.db_path.exists():
        print("❌ Database file does not exist")
        print(f"   Expected at: {db.db_path}")
        return

    try:
        status = await db.get_migration_status()
        print(f"📁 Database: {db.db_path}")
        print(f"📊 Total migrations: {status['total_migrations']}")
        print(f"✅ Applied: {status['applied_count']}")
        print(f"⏳ Pending: {status['pending_count']}")

        if status['latest_applied']:
            print(f"🏷️  Latest applied: {status['latest_applied']}")
        else:
            print("🏷️  Latest applied: None (fresh database)")

        if status['next_pending']:
            print(f"⏭️  Next pending: {status['next_pending']}")
        else:
            print("⏭️  Next pending: None (up to date)")

        if status['applied_migrations']:
            print(f"\n📝 Applied migrations:")
            for version in status['applied_migrations']:
                print(f"   ✅ {version}")

        if status['pending_migrations']:
            print(f"\n⏳ Pending migrations:")
            for version in status['pending_migrations']:
                print(f"   ⏳ {version}")

    except Exception as e:
        logger.error(f"Failed to get migration status: {e}")


async def run_migrations(db: Database, target_version: str = None):
    """Run database migrations."""
    if target_version:
        print(f"🚀 Running migrations up to version {target_version}...")
    else:
        print("🚀 Running all pending migrations...")

    try:
        if target_version:
            await db.migrate_to_version(target_version)
        else:
            await db.initialize()

        print("✅ Migrations completed successfully!")
        await show_migration_status(db)

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise


async def rollback_migrations(db: Database, target_version: str):
    """Rollback database migrations."""
    print(f"⬇️  Rolling back to version {target_version}...")

    try:
        await db.rollback_to_version(target_version)
        print("✅ Rollback completed successfully!")
        await show_migration_status(db)

    except Exception as e:
        logger.error(f"Rollback failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())