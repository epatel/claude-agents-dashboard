"""Strip the redundant "[1m]" suffix from natively-1M Opus models.

Per Claude Code's model-config docs, Opus 4.7 and later run with the 1M context
window by default; "[1m]" has no effect on them. The dashboard no longer offers
the "(1M)" variants of claude-opus-5 / claude-opus-4-8 / claude-opus-4-7, so a
stored row still carrying the suffix would match no picker option.

Rewrite those items / agent_config rows to the bare id. Opus 4.6 and Sonnet 4.6
still need the opt-in and keep their "[1m]" values.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite

NATIVE_1M_MODELS = ("claude-opus-5", "claude-opus-4-8", "claude-opus-4-7")


class StripRedundant1MSuffixMigration(Migration):

    def __init__(self):
        super().__init__(
            version="032",
            description="Strip redundant [1m] suffix from natively-1M Opus models"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        for table in ("items", "agent_config"):
            for model in NATIVE_1M_MODELS:
                await db.execute(
                    f"UPDATE {table} SET model = ? WHERE model = ?",
                    (model, f"{model}[1m]"),
                )

    async def down(self, db: aiosqlite.Connection) -> None:
        # Irreversible: once stripped, a row that opted into [1m] can't be told
        # apart from one that never did, and both run at 1M anyway. No-op
        # (matches migration 027).
        pass
