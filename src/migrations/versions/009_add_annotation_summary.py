"""Add annotation_summary column to attachments table.

Stores a text summary of annotations (e.g., "2 arrows, 1 circle").
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class AddAnnotationSummaryMigration(Migration):

    def __init__(self):
        super().__init__(
            version="009",
            description="Add annotation_summary column to attachments"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        await db.execute("""
            ALTER TABLE attachments
            ADD COLUMN annotation_summary TEXT DEFAULT NULL
        """)

    async def down(self, db: aiosqlite.Connection) -> None:
        await db.execute("""
            ALTER TABLE attachments
            DROP COLUMN annotation_summary
        """)
