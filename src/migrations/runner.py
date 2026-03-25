"""Migration runner for managing database schema changes."""

import os
import importlib.util
import logging
from pathlib import Path
from typing import List, Dict, Optional
import aiosqlite
from datetime import datetime

from .migration import Migration

logger = logging.getLogger(__name__)


class MigrationRunner:
    """Manages and runs database migrations."""

    def __init__(self, migrations_dir: Path):
        self.migrations_dir = migrations_dir
        self._migrations: Dict[str, Migration] = {}
        self._discovered = False

    async def _ensure_migrations_table(self, db: aiosqlite.Connection) -> None:
        """Create migrations table if it doesn't exist."""
        await db.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

    async def _discover_migrations(self) -> None:
        """Discover and load migration files."""
        if self._discovered:
            return

        if not self.migrations_dir.exists():
            logger.warning(f"Migrations directory {self.migrations_dir} does not exist")
            self._discovered = True
            return

        for file_path in sorted(self.migrations_dir.glob("*.py")):
            if file_path.name.startswith("__"):
                continue

            try:
                # Extract version from filename (e.g., "001_initial_schema.py" -> "001")
                version = file_path.stem.split("_")[0]

                # Load module dynamically
                spec = importlib.util.spec_from_file_location(
                    f"migration_{version}", file_path
                )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                # Find Migration class in module
                migration_class = None
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (isinstance(attr, type) and
                        issubclass(attr, Migration) and
                        attr != Migration):
                        migration_class = attr
                        break

                if migration_class:
                    migration = migration_class()
                    self._migrations[version] = migration
                    logger.debug(f"Loaded migration: {migration}")
                else:
                    logger.warning(f"No Migration class found in {file_path}. Available classes: {[name for name in dir(module) if not name.startswith('_')]}")

            except Exception as e:
                logger.error(f"Failed to load migration {file_path}: {e}")

        self._discovered = True

    async def get_applied_migrations(self, db: aiosqlite.Connection) -> List[str]:
        """Get list of applied migration versions."""
        await self._ensure_migrations_table(db)

        cursor = await db.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def get_pending_migrations(self, db: aiosqlite.Connection) -> List[Migration]:
        """Get list of pending migrations."""
        await self._discover_migrations()
        applied = await self.get_applied_migrations(db)

        pending = []
        for version in sorted(self._migrations.keys()):
            if version not in applied:
                pending.append(self._migrations[version])

        return pending

    async def apply_migration(self, db: aiosqlite.Connection, migration: Migration) -> None:
        """Apply a single migration."""
        logger.info(f"Applying migration: {migration}")

        try:
            await migration.up(db)

            # Record migration as applied
            await db.execute(
                "INSERT INTO schema_migrations (version, description) VALUES (?, ?)",
                (migration.version, migration.description)
            )

            logger.info(f"Successfully applied migration: {migration}")

        except Exception as e:
            logger.error(f"Failed to apply migration {migration}: {e}")
            raise

    async def rollback_migration(self, db: aiosqlite.Connection, migration: Migration) -> None:
        """Rollback a single migration."""
        logger.info(f"Rolling back migration: {migration}")

        try:
            await migration.down(db)

            # Remove migration record
            await db.execute(
                "DELETE FROM schema_migrations WHERE version = ?",
                (migration.version,)
            )

            logger.info(f"Successfully rolled back migration: {migration}")

        except Exception as e:
            logger.error(f"Failed to rollback migration {migration}: {e}")
            raise

    async def migrate_up(self, db: aiosqlite.Connection, target_version: Optional[str] = None) -> None:
        """Apply all pending migrations or up to a specific version."""
        pending = await self.get_pending_migrations(db)

        if target_version:
            # Filter to only migrations up to target version
            pending = [m for m in pending if m.version <= target_version]

        if not pending:
            logger.info("No pending migrations to apply")
            return

        logger.info(f"Applying {len(pending)} pending migrations")

        for migration in pending:
            await self.apply_migration(db, migration)
            await db.commit()

    async def migrate_down(self, db: aiosqlite.Connection, target_version: str) -> None:
        """Rollback migrations down to a specific version."""
        await self._discover_migrations()
        applied = await self.get_applied_migrations(db)

        # Find migrations to rollback (in reverse order)
        to_rollback = []
        for version in reversed(sorted(applied)):
            if version > target_version:
                if version in self._migrations:
                    to_rollback.append(self._migrations[version])
                else:
                    logger.warning(f"Migration {version} is applied but file not found")

        if not to_rollback:
            logger.info(f"No migrations to rollback to version {target_version}")
            return

        logger.info(f"Rolling back {len(to_rollback)} migrations")

        for migration in to_rollback:
            await self.rollback_migration(db, migration)
            await db.commit()

    async def get_status(self, db: aiosqlite.Connection) -> Dict[str, any]:
        """Get migration status information."""
        await self._discover_migrations()
        applied = await self.get_applied_migrations(db)
        pending = await self.get_pending_migrations(db)

        return {
            "total_migrations": len(self._migrations),
            "applied_count": len(applied),
            "pending_count": len(pending),
            "applied_migrations": applied,
            "pending_migrations": [m.version for m in pending],
            "latest_applied": applied[-1] if applied else None,
            "next_pending": pending[0].version if pending else None
        }