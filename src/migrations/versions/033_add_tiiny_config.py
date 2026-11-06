"""Add Tiiny provider config to agent_config.

Backs the Settings ▸ Tiiny tab (experimental). Tiiny is a local-provider
profile of the Claude runtime: the SDK is pointed at the device's
Anthropic-compatible endpoint through the TiinyOS PC Server.

- tiiny_enabled         — route tiiny/* models to the device
- tiiny_base_url        — Anthropic-protocol endpoint (default http://anthropic.api.tiiny)
- tiiny_load_claude_md  — inject the worktree CLAUDE.md into the prompt (the
                          local profile's setting_sources=["local"] skips it)

The API key is deliberately NOT a column: it comes from $TIINY_API_KEY or the
macOS Keychain, so it never lands in the target project's agents-lab/ DB.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class AddTiinyConfigMigration(Migration):

    def __init__(self):
        super().__init__(
            version="033",
            description="Add Tiiny provider config to agent_config"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        await db.execute(
            "ALTER TABLE agent_config ADD COLUMN tiiny_enabled INTEGER DEFAULT 0"
        )
        await db.execute(
            "ALTER TABLE agent_config ADD COLUMN tiiny_base_url TEXT DEFAULT 'http://anthropic.api.tiiny'"
        )
        await db.execute(
            "ALTER TABLE agent_config ADD COLUMN tiiny_load_claude_md INTEGER DEFAULT 0"
        )

    async def down(self, db: aiosqlite.Connection) -> None:
        # SQLite column-add migrations leave the columns on rollback — match the
        # no-op pattern used by the other column-add migrations (022, 028, 030).
        pass
