"""Small helpers shared by the route modules."""

from fastapi import Request


# --- Work log ---

async def _item_rows(request: Request, sql: str, item_id: str) -> list[dict]:
    """Rows of a one-parameter ``... WHERE item_id = ?`` query, as dicts."""
    async with request.app.state.db.connect() as conn:
        cursor = await conn.execute(sql, (item_id,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
