"""Database service for handling all database operations."""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..database import Database
from ..agent.session import AgentResult

logger = logging.getLogger(__name__)


class DatabaseService:
    """Handles all database operations for items, logs, and related data."""

    def __init__(self, db: Database):
        self.db = db

    async def get_all_items(self) -> List[Dict[str, Any]]:
        """Get all items ordered by column and position."""
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT i.id, i.title, i.description, i.column_name, i.status,"
                " COALESCE(wl.cnt, 0) AS log_count"
                " FROM items i"
                " LEFT JOIN (SELECT item_id, COUNT(*) AS cnt FROM work_log GROUP BY item_id) wl"
                " ON i.id = wl.item_id"
                " ORDER BY i.column_name, i.position"
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_item(self, item_id: str) -> Optional[Dict[str, Any]]:
        """Get an item by ID."""
        async with self.db.connect() as conn:
            cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def update_item(self, item_id: str, **kwargs) -> Dict[str, Any]:
        """Update an item with the given fields."""
        async with self.db.connect() as conn:
            # If column_name is being changed, assign next position in target column
            if "column_name" in kwargs and "position" not in kwargs:
                target_column = kwargs["column_name"]
                cursor = await conn.execute(
                    "SELECT COALESCE(MAX(position), -1) + 1 FROM items WHERE column_name = ?",
                    (target_column,)
                )
                row = await cursor.fetchone()
                kwargs["position"] = row[0]

            sets = ", ".join(f"{k} = ?" for k in kwargs)
            vals = list(kwargs.values()) + [item_id]
            await conn.execute(
                f"UPDATE items SET {sets}, updated_at = datetime('now') WHERE id = ?",
                vals,
            )
            await conn.commit()
            cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
            item = dict(await cursor.fetchone())
        return item

    async def log_entry(self, item_id: str, entry_type: str, content: str, metadata: Optional[str] = None):
        """Add a log entry for an item."""
        async with self.db.connect() as conn:
            await conn.execute(
                "INSERT INTO work_log (item_id, entry_type, content, metadata) VALUES (?, ?, ?, ?)",
                (item_id, entry_type, content, metadata),
            )
            await conn.commit()

    async def get_agent_config(self) -> Dict[str, Any]:
        """Get the agent configuration."""
        async with self.db.connect() as conn:
            cursor = await conn.execute("SELECT * FROM agent_config WHERE id = 1")
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return {}

    async def create_todo_item(self, title: str, description: str) -> Dict[str, Any]:
        """Create a new todo item and return it."""
        from ..models import new_id

        todo_id = new_id()

        async with self.db.connect() as conn:
            # Get next position in todo column
            cursor = await conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM items WHERE column_name = 'todo'"
            )
            row = await cursor.fetchone()
            position = row[0] if row else 0

            # Create new todo item
            await conn.execute(
                "INSERT INTO items (id, title, description, column_name, position) VALUES (?, ?, ?, 'todo', ?)",
                (todo_id, title, description, position),
            )
            await conn.commit()

            # Get the created item
            cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (todo_id,))
            item = dict(await cursor.fetchone())

        return item

    async def store_clarification(self, item_id: str, prompt: str, choices: Optional[List[str]]):
        """Store a question request in the database."""
        async with self.db.connect() as conn:
            await conn.execute(
                "INSERT INTO clarifications (item_id, prompt, choices) VALUES (?, ?, ?)",
                (item_id, prompt, json.dumps(choices) if choices else None),
            )
            await conn.commit()

    async def update_clarification_response(self, item_id: str, response: str):
        """Update question with user response."""
        async with self.db.connect() as conn:
            await conn.execute(
                "UPDATE clarifications SET response = ?, answered_at = datetime('now') "
                "WHERE item_id = ? AND response IS NULL",
                (response, item_id),
            )
            await conn.commit()

    async def store_review_comments(self, item_id: str, comments: List[str]):
        """Store review comments for an item."""
        async with self.db.connect() as conn:
            for comment in comments:
                await conn.execute(
                    "INSERT INTO review_comments (item_id, content) VALUES (?, ?)",
                    (item_id, comment),
                )
            await conn.commit()

    async def get_attachments(self, item_id: str) -> List[Dict[str, Any]]:
        """Get all attachments for an item."""
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT * FROM attachments WHERE item_id = ? ORDER BY created_at",
                (item_id,),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def save_token_usage(self, item_id: str, result: AgentResult):
        """Save token usage statistics to the database."""
        # Only save if we have meaningful data
        if not any([result.input_tokens, result.output_tokens, result.total_tokens, result.cost_usd]):
            return

        async with self.db.connect() as conn:
            await conn.execute("""
                INSERT INTO token_usage
                (item_id, session_id, input_tokens, output_tokens, total_tokens, cost_usd)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                item_id,
                result.session_id,
                result.input_tokens,
                result.output_tokens,
                result.total_tokens,
                result.cost_usd
            ))
            await conn.commit()

    async def save_allowed_command(self, command: str):
        """Add a command to the allowed_commands list in agent_config."""
        config = await self.get_agent_config()
        raw = config.get("allowed_commands", "[]")
        try:
            commands = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except (json.JSONDecodeError, TypeError):
            commands = []
        if command not in commands:
            commands.append(command)
            async with self.db.connect() as conn:
                await conn.execute(
                    "UPDATE agent_config SET allowed_commands = ?, updated_at = datetime('now') WHERE id = 1",
                    (json.dumps(commands),),
                )
                await conn.commit()
        return commands

    async def save_allowed_builtin_tool(self, tool_name: str):
        """Add a tool to the allowed_builtin_tools list in agent_config."""
        config = await self.get_agent_config()
        raw = config.get("allowed_builtin_tools", "[]")
        try:
            tools = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except (json.JSONDecodeError, TypeError):
            tools = []
        if tool_name not in tools:
            tools.append(tool_name)
            async with self.db.connect() as conn:
                await conn.execute(
                    "UPDATE agent_config SET allowed_builtin_tools = ?, updated_at = datetime('now') WHERE id = 1",
                    (json.dumps(tools),),
                )
                await conn.commit()
        return tools

    async def delete_item_and_related(self, item_id: str) -> Optional[Dict[str, Any]]:
        """Delete an item and all related records, return the deleted item."""
        async with self.db.connect() as conn:
            # Get item info before deletion
            cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
            item_row = await cursor.fetchone()
            item = dict(item_row) if item_row else None

            # Get attachment files for cleanup
            cursor2 = await conn.execute("SELECT asset_path FROM attachments WHERE item_id = ?", (item_id,))
            asset_paths = [row[0] for row in await cursor2.fetchall()]

            # Delete all related records
            await conn.execute("DELETE FROM attachments WHERE item_id = ?", (item_id,))
            await conn.execute("DELETE FROM work_log WHERE item_id = ?", (item_id,))
            await conn.execute("DELETE FROM review_comments WHERE item_id = ?", (item_id,))
            await conn.execute("DELETE FROM clarifications WHERE item_id = ?", (item_id,))
            await conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
            await conn.commit()

        # Clean up attachment files
        for asset_path in asset_paths:
            p = Path(asset_path)
            if p.exists():
                p.unlink()

        return item