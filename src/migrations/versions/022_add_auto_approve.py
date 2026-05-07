"""Add auto_approve flag to items.

When enabled, after the agent completes the dashboard runs a separate
review agent against the diff and the agent's last message. If the
reviewer approves, the item is auto-merged. If it requests changes, the
comments are sent back to the original agent. The cycle is capped at 3
return trips before falling back to human review.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class AddAutoApproveMigration(Migration):

    def __init__(self):
        super().__init__(
            version="022",
            description="Add auto_approve flag to items"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        await db.execute(
            "ALTER TABLE items ADD COLUMN auto_approve INTEGER DEFAULT 0"
        )

    async def down(self, db: aiosqlite.Connection) -> None:
        # SQLite 3.35+ supports DROP COLUMN; older versions require full
        # table recreation. Match the no-op pattern used by other column-add
        # migrations (021) — leave the column on rollback.
        pass
