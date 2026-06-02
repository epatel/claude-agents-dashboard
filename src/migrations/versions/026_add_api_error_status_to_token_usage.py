"""Add api_error_status to token_usage.

When an agent run fails on an API call, the SDK's ResultMessage carries an
`api_error_status` HTTP code (429/500/502/503/529, ...). Persisting it lets the
dashboard distinguish transient/retryable API failures from real task errors,
and keeps an auditable record alongside the run's token/cost row.

Nullable: only populated on failed runs that hit an API error; successful runs
and non-API failures leave it NULL.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class AddApiErrorStatusToTokenUsageMigration(Migration):

    def __init__(self):
        super().__init__(
            version="026",
            description="Add api_error_status to token_usage for API failure classification"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        await db.execute(
            "ALTER TABLE token_usage ADD COLUMN api_error_status INTEGER"
        )

    async def down(self, db: aiosqlite.Connection) -> None:
        # Match the no-op rollback pattern used by other column-add migrations
        # (021, 022, 025) — leave the column on rollback.
        pass
