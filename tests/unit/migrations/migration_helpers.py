"""Shared helpers for the migration tests: load a real migration by file name,
and scratch SQLite databases to run it against.

A plain module, not a conftest: test modules import what they need explicitly.
"""

import importlib.util
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

# The runner's bookkeeping table, as the runner tests create it up front.
SCHEMA_MIGRATIONS_TABLE = """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                description TEXT,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """

VERSIONS_DIR = Path(__file__).resolve().parents[3] / "src" / "migrations" / "versions"


def load_migration(filename, class_name):
    """Import the real migration module ``filename`` by file path and return a ``class_name`` instance."""
    spec = importlib.util.spec_from_file_location(f"migration_{filename[:3]}", VERSIONS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, class_name)()


@asynccontextmanager
async def scratch_db(*statements):
    """A temporary aiosqlite connection (``Row`` factory) with ``statements`` run and committed.

    Each statement is SQL, or (SQL, params) — a list of param tuples runs it with executemany.
    """
    with tempfile.TemporaryDirectory() as tmp:
        conn = await aiosqlite.connect(str(Path(tmp) / "test.db"))
        conn.row_factory = aiosqlite.Row
        for statement in statements:
            sql, params = (statement, ()) if isinstance(statement, str) else statement
            if isinstance(params, list):
                await conn.executemany(sql, params)
            else:
                await conn.execute(sql, params)
        await conn.commit()
        try:
            yield conn
        finally:
            await conn.close()


async def columns_of(db, table):
    """The column names of ``table``."""
    cur = await db.execute(f"PRAGMA table_info({table})")
    return {row["name"] for row in await cur.fetchall()}


async def model_of(db, table, key, key_col="id"):
    """The ``model`` column of the ``table`` row whose ``key_col`` is ``key``."""
    cur = await db.execute(f"SELECT model FROM {table} WHERE {key_col} = ?", (key,))
    return (await cur.fetchone())["model"]


async def applied_count(db, version):
    """How many schema_migrations rows record ``version``."""
    cursor = await db.execute("SELECT COUNT(*) FROM schema_migrations WHERE version = ?", (version,))
    return (await cursor.fetchone())[0]


async def table_exists(db, name):
    """Whether a table called ``name`` exists."""
    cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return await cursor.fetchone() is not None
