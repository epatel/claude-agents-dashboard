import aiosqlite
import logging
from pathlib import Path
from contextlib import asynccontextmanager
try:
    from .migrations import MigrationRunner
except ImportError:
    # Handle direct execution case
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).parent))
    from migrations import MigrationRunner

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        # Initialize migration runner
        migrations_dir = Path(__file__).parent / "migrations" / "versions"
        self.migration_runner = MigrationRunner(migrations_dir)

    async def initialize(self):
        """Initialize database and run any pending migrations."""
        async with self.connect() as db:
            # Run migrations to set up or update schema
            await self.migration_runner.migrate_up(db)
            await db.commit()

    async def get_migration_status(self):
        """Get current migration status information."""
        async with self.connect() as db:
            return await self.migration_runner.get_status(db)

    async def migrate_to_version(self, version: str):
        """Migrate database to a specific version."""
        async with self.connect() as db:
            await self.migration_runner.migrate_up(db, version)
            await db.commit()

    async def rollback_to_version(self, version: str):
        """Rollback database to a specific version."""
        async with self.connect() as db:
            await self.migration_runner.migrate_down(db, version)
            await db.commit()

    @asynccontextmanager
    async def connect(self):
        db = await aiosqlite.connect(self.db_path)
        db.row_factory = aiosqlite.Row
        try:
            yield db
        finally:
            await db.close()
