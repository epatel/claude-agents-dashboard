"""Upgrade selectable models to Opus 4.7 / Sonnet 4.6."""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


# (old, new) model ids this migration moves rows between.
_RENAMES = (
    ("claude-opus-4-6", "claude-opus-4-7"),
    ("claude-sonnet-4-20250514", "claude-sonnet-4-6"),
    ("claude-sonnet-4-20250514+advisor", "claude-sonnet-4-6+advisor"),
)


async def _rename_models(db: aiosqlite.Connection, table: str, renames) -> None:
    """Set ``model`` to ``new`` on every ``table`` row whose model is ``old``, per (old, new)."""
    for old, new in renames:
        await db.execute(
            f"UPDATE {table} SET model = '{new}' WHERE model = '{old}'"
        )


class UpgradeSelectableModelsMigration(Migration):
    """Shift existing rows from Opus 4.6 → 4.7 and Sonnet 4 (dated) → Sonnet 4.6."""

    def __init__(self):
        super().__init__(
            version="019",
            description="Upgrade default model to Claude Opus 4.7; migrate Sonnet 4 → 4.6"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        await _rename_models(db, "items", _RENAMES[:1])
        await db.execute(
            "UPDATE items SET model = 'claude-opus-4-7' WHERE model IS NULL"
        )
        await _rename_models(db, "items", _RENAMES[1:])
        await _rename_models(db, "agent_config", _RENAMES)

    async def down(self, db: aiosqlite.Connection) -> None:
        reverted = [(new, old) for old, new in _RENAMES]
        await _rename_models(db, "items", reverted)
        await _rename_models(db, "agent_config", reverted)
