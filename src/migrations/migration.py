"""Base migration class for database schema changes."""

from abc import ABC, abstractmethod
from typing import Any
import aiosqlite


class Migration(ABC):
    """Base class for database migrations."""

    def __init__(self, version: str, description: str):
        self.version = version
        self.description = description

    @abstractmethod
    async def up(self, db: aiosqlite.Connection) -> None:
        """Apply the migration."""
        pass

    @abstractmethod
    async def down(self, db: aiosqlite.Connection) -> None:
        """Rollback the migration."""
        pass

    def __str__(self) -> str:
        return f"Migration {self.version}: {self.description}"

    def __repr__(self) -> str:
        return f"Migration(version='{self.version}', description='{self.description}')"