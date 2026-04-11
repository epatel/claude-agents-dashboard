"""Add has_file_changes flag to items.

When an agent completes and moves to review, this flag indicates whether
the agent produced any file changes. Cards show 'Done' vs 'Approve & Merge'
based on this flag.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class AddHasFileChangesMigration(Migration):

    def __init__(self):
        super().__init__(
            version="015",
            description="Add has_file_changes flag to items"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        await db.execute(
            "ALTER TABLE items ADD COLUMN has_file_changes INTEGER DEFAULT NULL"
        )

    async def down(self, db: aiosqlite.Connection) -> None:
        await db.execute("""
            CREATE TABLE items_backup AS SELECT
                id, title, description, column_name, position, status,
                branch_name, worktree_path, session_id, model,
                commit_message, created_at, updated_at, base_branch,
                base_commit, done_at, merge_commit, epic_id, auto_start,
                start_copy
            FROM items
        """)
        await db.execute("DROP TABLE items")
        await db.execute("ALTER TABLE items_backup RENAME TO items")
