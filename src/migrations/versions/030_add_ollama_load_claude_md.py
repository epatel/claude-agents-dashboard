"""Add ollama_load_claude_md flag to agent_config.

Backs the Settings ▸ Ollama tab toggle "Load project CLAUDE.md".

The Ollama path uses setting_sources=["local"], which intentionally skips
auto-loading the target project's CLAUDE.md (to keep context small for small
local models). When this flag is on, session.py injects the worktree CLAUDE.md
into the system prompt so project conventions reach Ollama agents — matching the
Claude path's setting_sources=["project"] behaviour. Off by default to preserve
the lean-context default for small models.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class AddOllamaLoadClaudeMdMigration(Migration):

    def __init__(self):
        super().__init__(
            version="030",
            description="Add ollama_load_claude_md flag to agent_config"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        await db.execute(
            "ALTER TABLE agent_config ADD COLUMN ollama_load_claude_md INTEGER DEFAULT 0"
        )

    async def down(self, db: aiosqlite.Connection) -> None:
        # SQLite column-add migrations leave the column on rollback — match the
        # no-op pattern used by the other recent column-add migrations (022, 028).
        pass
