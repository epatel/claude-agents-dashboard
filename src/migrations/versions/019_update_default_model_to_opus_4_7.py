"""Upgrade selectable models to Opus 4.7 / Sonnet 4.6."""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class UpgradeSelectableModelsMigration(Migration):
    """Shift existing rows from Opus 4.6 → 4.7 and Sonnet 4 (dated) → Sonnet 4.6."""

    def __init__(self):
        super().__init__(
            version="019",
            description="Upgrade default model to Claude Opus 4.7; migrate Sonnet 4 → 4.6"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        await db.execute(
            "UPDATE items SET model = 'claude-opus-4-7' WHERE model = 'claude-opus-4-6'"
        )
        await db.execute(
            "UPDATE items SET model = 'claude-opus-4-7' WHERE model IS NULL"
        )
        await db.execute(
            "UPDATE items SET model = 'claude-sonnet-4-6' WHERE model = 'claude-sonnet-4-20250514'"
        )
        await db.execute(
            "UPDATE items SET model = 'claude-sonnet-4-6+advisor' WHERE model = 'claude-sonnet-4-20250514+advisor'"
        )
        await db.execute(
            "UPDATE agent_config SET model = 'claude-opus-4-7' WHERE model = 'claude-opus-4-6'"
        )
        await db.execute(
            "UPDATE agent_config SET model = 'claude-sonnet-4-6' WHERE model = 'claude-sonnet-4-20250514'"
        )
        await db.execute(
            "UPDATE agent_config SET model = 'claude-sonnet-4-6+advisor' WHERE model = 'claude-sonnet-4-20250514+advisor'"
        )

    async def down(self, db: aiosqlite.Connection) -> None:
        await db.execute(
            "UPDATE items SET model = 'claude-opus-4-6' WHERE model = 'claude-opus-4-7'"
        )
        await db.execute(
            "UPDATE items SET model = 'claude-sonnet-4-20250514' WHERE model = 'claude-sonnet-4-6'"
        )
        await db.execute(
            "UPDATE items SET model = 'claude-sonnet-4-20250514+advisor' WHERE model = 'claude-sonnet-4-6+advisor'"
        )
        await db.execute(
            "UPDATE agent_config SET model = 'claude-opus-4-6' WHERE model = 'claude-opus-4-7'"
        )
        await db.execute(
            "UPDATE agent_config SET model = 'claude-sonnet-4-20250514' WHERE model = 'claude-sonnet-4-6'"
        )
        await db.execute(
            "UPDATE agent_config SET model = 'claude-sonnet-4-20250514+advisor' WHERE model = 'claude-sonnet-4-6+advisor'"
        )
