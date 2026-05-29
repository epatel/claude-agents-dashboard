"""Add use_chrome flag to items.

When enabled, the item's agent is launched with the `claude` CLI's
`--chrome` flag, which registers the Claude-in-Chrome MCP server and exposes
browser tools (navigate, read_page, computer, ...) to the agent. The task
prompt is also annotated so the agent knows it has a browser available.

Per-task: code-focused tasks leave this off; browser tasks turn it on.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class AddUseChromeToItemsMigration(Migration):

    def __init__(self):
        super().__init__(
            version="025",
            description="Add use_chrome flag to items for browser-enabled tasks"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        await db.execute(
            "ALTER TABLE items ADD COLUMN use_chrome INTEGER DEFAULT 0"
        )

    async def down(self, db: aiosqlite.Connection) -> None:
        # Match the no-op rollback pattern used by other column-add migrations
        # (021, 022) — leave the column on rollback.
        pass
