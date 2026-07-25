"""Update the default model from Claude Opus 4.8 to Claude Opus 5.

Mirrors migrations 019 / 024: bump any items / agent_config rows still pointing
at the previous default (claude-opus-4-8) to the new default (claude-opus-5).
The 1M variant is migrated in lockstep (claude-opus-4-8[1m] -> claude-opus-5[1m])
so users who opted into the extended context window keep it.

Only rows that match the *old default* are touched — explicit user choices of
other models (fable, sonnet, haiku, older opus) are deliberately left alone.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class UpdateDefaultModelToOpus5Migration(Migration):
    """Bump the stored default model from claude-opus-4-8 to claude-opus-5."""

    def __init__(self):
        super().__init__(
            version="031",
            description="Update default model to Claude Opus 5"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        """Bump items / agent_config rows on the old default to the new default."""
        for table in ("items", "agent_config"):
            await db.execute(
                f"UPDATE {table} SET model = 'claude-opus-5' WHERE model = 'claude-opus-4-8'"
            )
            await db.execute(
                f"UPDATE {table} SET model = 'claude-opus-5[1m]' "
                "WHERE model = 'claude-opus-4-8[1m]'"
            )

    async def down(self, db: aiosqlite.Connection) -> None:
        """Revert items / agent_config rows back to the previous default."""
        for table in ("items", "agent_config"):
            await db.execute(
                f"UPDATE {table} SET model = 'claude-opus-4-8' WHERE model = 'claude-opus-5'"
            )
            await db.execute(
                f"UPDATE {table} SET model = 'claude-opus-4-8[1m]' "
                "WHERE model = 'claude-opus-5[1m]'"
            )
