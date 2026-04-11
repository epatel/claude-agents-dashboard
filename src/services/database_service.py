"""Database service for handling all database operations."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..database import Database
from ..agent.session import AgentResult
from ..models import new_id

logger = logging.getLogger(__name__)

# Whitelist of columns that may be set via update_item()
ALLOWED_ITEM_COLUMNS = {
    "title", "description", "column_name", "status", "position",
    "branch_name", "worktree_path", "session_id", "model",
    "base_branch", "base_commit", "done_at", "epic_id",
    "merge_commit", "auto_start", "commit_message",
    "has_file_changes",
}

# Whitelist of columns that may be set via update_epic()
ALLOWED_EPIC_COLUMNS = {
    "title", "color", "position",
}


class DatabaseService:
    """Handles all database operations for items, logs, and related data."""

    def __init__(self, db: Database):
        self.db = db

    async def get_all_items(self) -> List[Dict[str, Any]]:
        """Get all items ordered by column and position."""
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT i.id, i.title, i.description, i.column_name, i.status,"
                " i.done_at, i.updated_at, COALESCE(wl.cnt, 0) AS log_count"
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
            cursor = await conn.execute(
                "SELECT i.*, COALESCE(wl.cnt, 0) AS log_count"
                " FROM items i"
                " LEFT JOIN (SELECT item_id, COUNT(*) AS cnt FROM work_log GROUP BY item_id) wl"
                " ON i.id = wl.item_id"
                " WHERE i.id = ?",
                (item_id,),
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def update_item(self, item_id: str, **kwargs) -> Dict[str, Any]:
        """Update an item with the given fields."""
        invalid_keys = set(kwargs) - ALLOWED_ITEM_COLUMNS
        if invalid_keys:
            raise ValueError(f"Invalid item column(s): {invalid_keys}")

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

            # Auto-set done_at when moving to done, clear when leaving
            if "column_name" in kwargs:
                if kwargs["column_name"] == "done" and "done_at" not in kwargs:
                    kwargs["done_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
                elif kwargs["column_name"] != "done":
                    kwargs["done_at"] = None

            sets = ", ".join(f"{k} = ?" for k in kwargs)
            vals = list(kwargs.values()) + [item_id]
            await conn.execute(
                f"UPDATE items SET {sets}, updated_at = datetime('now') WHERE id = ?",
                vals,
            )
            await conn.commit()
            cursor = await conn.execute(
                "SELECT i.*, COALESCE(wl.cnt, 0) AS log_count"
                " FROM items i"
                " LEFT JOIN (SELECT item_id, COUNT(*) AS cnt FROM work_log GROUP BY item_id) wl"
                " ON i.id = wl.item_id"
                " WHERE i.id = ?",
                (item_id,),
            )
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

    async def create_todo_item(self, title: str, description: str, epic_id: str = None, auto_start: bool = False, start_copy: bool = False) -> Dict[str, Any]:
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
                "INSERT INTO items (id, title, description, column_name, position, epic_id, auto_start, start_copy) VALUES (?, ?, ?, 'todo', ?, ?, ?, ?)",
                (todo_id, title, description, position, epic_id, auto_start, int(start_copy)),
            )
            await conn.commit()

            # Get the created item
            cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (todo_id,))
            item = dict(await cursor.fetchone())

        return item

    async def copy_item(self, item_id: str) -> Dict[str, Any]:
        """Copy an item (title, description, model) and its attachments. Returns the new item."""
        import shutil
        from ..models import new_id

        item = await self.get_item(item_id)
        if not item:
            raise ValueError(f"Item {item_id} not found")

        copy_id = new_id()

        async with self.db.connect() as conn:
            # Get next position in todo column
            cursor = await conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM items WHERE column_name = 'todo'"
            )
            row = await cursor.fetchone()
            position = row[0] if row else 0

            # Create copied item
            await conn.execute(
                "INSERT INTO items (id, title, description, column_name, position, model, start_copy) VALUES (?, ?, ?, 'todo', ?, ?, ?)",
                (copy_id, item["title"], item.get("description", ""), position, item.get("model"), item.get("start_copy", 0)),
            )

            # Copy attachments
            attachments = await self.get_attachments(item_id)
            for att in attachments:
                src_path = Path(att["asset_path"])
                if src_path.exists():
                    # Create new asset with unique name
                    new_filename = f"{copy_id}_{src_path.name}"
                    dst_path = src_path.parent / new_filename
                    shutil.copy2(str(src_path), str(dst_path))
                    await conn.execute(
                        "INSERT INTO attachments (item_id, filename, asset_path) VALUES (?, ?, ?)",
                        (copy_id, att["filename"], str(dst_path)),
                    )

            await conn.commit()

            cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (copy_id,))
            new_item = dict(await cursor.fetchone())

        return new_item

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
            await conn.execute("DELETE FROM item_dependencies WHERE item_id = ? OR requires_item_id = ?", (item_id, item_id))
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

    # --- Epic operations ---

    async def get_epics(self) -> List[Dict[str, Any]]:
        """Get all epics ordered by position."""
        async with self.db.connect() as conn:
            cursor = await conn.execute("SELECT * FROM epics ORDER BY position, created_at")
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def create_epic(self, title: str, color: str) -> Dict[str, Any]:
        """Create a new epic."""
        epic_id = new_id()
        async with self.db.connect() as conn:
            cursor = await conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM epics")
            row = await cursor.fetchone()
            position = row[0]

            await conn.execute(
                "INSERT INTO epics (id, title, color, position) VALUES (?, ?, ?, ?)",
                (epic_id, title, color, position),
            )
            await conn.commit()

            cursor = await conn.execute("SELECT * FROM epics WHERE id = ?", (epic_id,))
            return dict(await cursor.fetchone())

    async def update_epic(self, epic_id: str, **kwargs) -> Optional[Dict[str, Any]]:
        """Update an epic's fields."""
        invalid_keys = set(kwargs) - ALLOWED_EPIC_COLUMNS
        if invalid_keys:
            raise ValueError(f"Invalid epic column(s): {invalid_keys}")

        async with self.db.connect() as conn:
            updates = []
            values = []
            for field, value in kwargs.items():
                if value is not None:
                    updates.append(f"{field} = ?")
                    values.append(value)

            if updates:
                values.append(epic_id)
                await conn.execute(
                    f"UPDATE epics SET {', '.join(updates)} WHERE id = ?",
                    values,
                )
                await conn.commit()

            cursor = await conn.execute("SELECT * FROM epics WHERE id = ?", (epic_id,))
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def delete_epic(self, epic_id: str) -> Optional[Dict[str, Any]]:
        """Delete an epic and nullify epic_id on related items."""
        async with self.db.connect() as conn:
            cursor = await conn.execute("SELECT * FROM epics WHERE id = ?", (epic_id,))
            row = await cursor.fetchone()
            if not row:
                return None
            epic = dict(row)

            await conn.execute("UPDATE items SET epic_id = NULL WHERE epic_id = ?", (epic_id,))
            await conn.execute("DELETE FROM epics WHERE id = ?", (epic_id,))
            await conn.commit()

        return epic

    # --- Dependency operations ---

    async def get_item_dependencies(self, item_id: str) -> List[Dict[str, Any]]:
        """Get items that this item depends on (requires)."""
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT i.id, i.title, i.column_name, i.status "
                "FROM item_dependencies d "
                "JOIN items i ON d.requires_item_id = i.id "
                "WHERE d.item_id = ?",
                (item_id,),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def set_item_dependencies(self, item_id: str, required_ids: List[str]) -> List[Dict[str, Any]]:
        """Replace all dependencies for an item with the given list of required item IDs."""
        async with self.db.connect() as conn:
            # Validate that all required items exist and none is self-referential
            for rid in required_ids:
                if rid == item_id:
                    raise ValueError("An item cannot depend on itself")
                cursor = await conn.execute("SELECT id FROM items WHERE id = ?", (rid,))
                if not await cursor.fetchone():
                    raise ValueError(f"Required item {rid} not found")

            # Replace: delete existing, insert new
            await conn.execute("DELETE FROM item_dependencies WHERE item_id = ?", (item_id,))
            for rid in required_ids:
                await conn.execute(
                    "INSERT OR IGNORE INTO item_dependencies (item_id, requires_item_id) VALUES (?, ?)",
                    (item_id, rid),
                )
            await conn.commit()

        return await self.get_item_dependencies(item_id)

    async def is_item_blocked(self, item_id: str) -> bool:
        """Check if any required item is not in done or archive."""
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM item_dependencies d "
                "JOIN items i ON d.requires_item_id = i.id "
                "WHERE d.item_id = ? AND i.column_name NOT IN ('done', 'archive')",
                (item_id,),
            )
            row = await cursor.fetchone()
            return row[0] > 0

    async def get_blocking_items(self, item_id: str) -> List[Dict[str, Any]]:
        """Get items that are blocking this one (required but not yet done/archived)."""
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT i.id, i.title, i.column_name, i.status "
                "FROM item_dependencies d "
                "JOIN items i ON d.requires_item_id = i.id "
                "WHERE d.item_id = ? AND i.column_name NOT IN ('done', 'archive')",
                (item_id,),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_dependent_items(self, item_id: str) -> List[str]:
        """Get IDs of items that depend on the given item."""
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT item_id FROM item_dependencies WHERE requires_item_id = ?",
                (item_id,),
            )
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def get_all_blocked_status(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get blocking items for all todo items that have unresolved dependencies.

        Returns a dict mapping item_id -> list of blocking item dicts (id, title).
        Only includes items that ARE blocked (have at least one unfinished dependency).
        """
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT d.item_id, i.id as blocking_id, i.title as blocking_title "
                "FROM item_dependencies d "
                "JOIN items i ON d.requires_item_id = i.id "
                "JOIN items target ON d.item_id = target.id "
                "WHERE target.column_name = 'todo' "
                "AND i.column_name NOT IN ('done', 'archive')"
            )
            rows = await cursor.fetchall()
            result: Dict[str, List[Dict[str, Any]]] = {}
            for row in rows:
                item_id = row[0]
                if item_id not in result:
                    result[item_id] = []
                result[item_id].append({"id": row[1], "title": row[2]})
            return result

    async def get_epic_progress(self) -> Dict[str, Dict[str, int]]:
        """Get item counts per column per epic."""
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT epic_id, column_name, COUNT(*) as cnt "
                "FROM items WHERE epic_id IS NOT NULL "
                "GROUP BY epic_id, column_name"
            )
            rows = await cursor.fetchall()

        progress = {}
        for row in rows:
            eid = row[0]
            col = row[1]
            cnt = row[2]
            if eid not in progress:
                progress[eid] = {"todo": 0, "doing": 0, "questions": 0, "review": 0, "done": 0, "archive": 0, "total": 0}
            progress[eid][col] = cnt
            if col != "archive":
                progress[eid]["total"] += cnt
        return progress