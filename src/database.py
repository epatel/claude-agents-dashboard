import aiosqlite
from pathlib import Path
from contextlib import asynccontextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    column_name   TEXT NOT NULL DEFAULT 'backlog',
    position      INTEGER NOT NULL DEFAULT 0,
    status        TEXT DEFAULT NULL,
    branch_name   TEXT DEFAULT NULL,
    worktree_path TEXT DEFAULT NULL,
    session_id    TEXT DEFAULT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS work_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id    TEXT NOT NULL REFERENCES items(id),
    timestamp  TEXT NOT NULL DEFAULT (datetime('now')),
    entry_type TEXT NOT NULL,
    content    TEXT NOT NULL,
    metadata   TEXT
);

CREATE TABLE IF NOT EXISTS review_comments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id     TEXT NOT NULL REFERENCES items(id),
    file_path   TEXT,
    line_number INTEGER,
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS clarifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id     TEXT NOT NULL REFERENCES items(id),
    prompt      TEXT NOT NULL,
    choices     TEXT,
    allow_text  INTEGER NOT NULL DEFAULT 1,
    response    TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    answered_at TEXT
);

CREATE TABLE IF NOT EXISTS agent_config (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    system_prompt   TEXT,
    tools           TEXT,
    model           TEXT DEFAULT 'claude-sonnet-4-20250514',
    project_context TEXT,
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    async def initialize(self):
        async with self.connect() as db:
            await db.executescript(SCHEMA)
            # Ensure default agent config row exists
            await db.execute(
                "INSERT OR IGNORE INTO agent_config (id) VALUES (1)"
            )
            await db.commit()

    @asynccontextmanager
    async def connect(self):
        db = await aiosqlite.connect(self.db_path)
        db.row_factory = aiosqlite.Row
        try:
            yield db
        finally:
            await db.close()
