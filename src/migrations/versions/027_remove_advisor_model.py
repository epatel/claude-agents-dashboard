"""Strip the removed "+advisor" suffix from stored models.

The experimental "Claude Sonnet 4.6 + Advisor" model (a `claude-...+advisor`
suffix that spun up an Opus advisor subagent) has been removed. The session
layer no longer parses the suffix, so any lingering `+advisor` model string
would now be passed to the SDK verbatim and fail.

Rewrite existing items / agent_config rows to the plain model id by dropping
the suffix (e.g. `claude-sonnet-4-6+advisor` -> `claude-sonnet-4-6`).
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class RemoveAdvisorModelMigration(Migration):

    def __init__(self):
        super().__init__(
            version="027",
            description="Strip removed +advisor suffix from stored models"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        # SQLite has no REPLACE-in-UPDATE shorthand issue here — replace()
        # leaves non-matching rows untouched, but scope the WHERE to be explicit.
        await db.execute(
            "UPDATE items SET model = REPLACE(model, '+advisor', '') "
            "WHERE model LIKE '%+advisor'"
        )
        await db.execute(
            "UPDATE agent_config SET model = REPLACE(model, '+advisor', '') "
            "WHERE model LIKE '%+advisor'"
        )

    async def down(self, db: aiosqlite.Connection) -> None:
        # Irreversible: the advisor model is gone, so there is nothing to
        # restore the suffix to. No-op (matches other data-cleanup migrations).
        pass
