"""Update the default model column from Claude Sonnet 4 to Claude Opus 4.6."""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class UpdateDefaultModelMigration(Migration):
    """Change the items.model column default to claude-opus-4-6."""

    def __init__(self):
        super().__init__(
            version="018",
            description="Update default model to Claude Opus 4.6"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        """Update existing items and config still using the old default model."""
        # Update items that have the old default model
        await db.execute(
            "UPDATE items SET model = 'claude-opus-4-6' WHERE model = 'claude-sonnet-4-20250514'"
        )
        # Update any NULL models
        await db.execute(
            "UPDATE items SET model = 'claude-opus-4-6' WHERE model IS NULL"
        )
        # Update agent_config default model
        await db.execute(
            "UPDATE agent_config SET model = 'claude-opus-4-6' WHERE model = 'claude-sonnet-4-20250514'"
        )

    async def down(self, db: aiosqlite.Connection) -> None:
        """Revert to old default model."""
        await db.execute(
            "UPDATE items SET model = 'claude-sonnet-4-20250514' WHERE model = 'claude-opus-4-6'"
        )
        await db.execute(
            "UPDATE agent_config SET model = 'claude-sonnet-4-20250514' WHERE model = 'claude-opus-4-6'"
        )
