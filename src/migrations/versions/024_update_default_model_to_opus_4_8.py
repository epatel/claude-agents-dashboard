"""Update the default model from Claude Opus 4.7 to Claude Opus 4.8.

Mirrors migration 019: bump any items / agent_config rows still pointing at the
previous default (claude-opus-4-7) to the new default (claude-opus-4-8).

Only rows that match the *old default* are touched — explicit user choices of
other models (sonnet, haiku, older opus) are deliberately left alone.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class UpdateDefaultModelToOpus48Migration(Migration):
    """Bump the stored default model from claude-opus-4-7 to claude-opus-4-8."""

    def __init__(self):
        super().__init__(
            version="024",
            description="Update default model to Claude Opus 4.8"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        """Bump items / agent_config rows on the old default to the new default."""
        # Items explicitly set to the previous default
        await db.execute(
            "UPDATE items SET model = 'claude-opus-4-8' WHERE model = 'claude-opus-4-7'"
        )
        # agent_config rows on the previous default
        await db.execute(
            "UPDATE agent_config SET model = 'claude-opus-4-8' WHERE model = 'claude-opus-4-7'"
        )

    async def down(self, db: aiosqlite.Connection) -> None:
        """Revert items / agent_config rows back to the previous default."""
        await db.execute(
            "UPDATE items SET model = 'claude-opus-4-7' WHERE model = 'claude-opus-4-8'"
        )
        await db.execute(
            "UPDATE agent_config SET model = 'claude-opus-4-7' WHERE model = 'claude-opus-4-8'"
        )
