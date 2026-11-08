"""Board-tool callbacks for WorkflowService.

The callbacks behind the board tools an agent session gets: create_todo /
create_epic / delete_todo, set_commit_message, create_shortcut, who_am_i,
view_board and graph_query (plus create_agent_todo, the same create_todo path
for out-of-process tool proxies). A mixin: it relies on the services
WorkflowService.__init__ sets up.
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from ..config import epic_plan_relpath
from ..constants import AUTO_APPROVE_MODES, AUTO_APPROVE_OFF

# Logged under the WorkflowService module's name, as before the split.
logger = logging.getLogger(__name__.rsplit(".", 1)[0] + ".workflow_service")


# create_todo options beyond title / description, with their defaults.
TODO_OPTION_DEFAULTS: Dict[str, Any] = {
    "epic_id": None,
    "requires": None,
    "autostart": False,
    "auto_approve": 0,
    "use_chrome": False,
}


def _todo_options(options: Dict[str, Any], function: str) -> Dict[str, Any]:
    """``options`` over ``TODO_OPTION_DEFAULTS``; an unknown name is a TypeError (naming ``function``)."""
    unknown = [name for name in options if name not in TODO_OPTION_DEFAULTS]
    if unknown:
        raise TypeError(f"{function}() got an unexpected keyword argument '{unknown[0]}'")
    return {**TODO_OPTION_DEFAULTS, **options}


class BoardToolCallbacksMixin:
    """Board-tool callback factories and their helpers (see module docstring)."""

    async def create_agent_todo(self, creator_item_id: str, title: str, description: str = "",
                                **options) -> Dict[str, Any]:
        """Create a todo on behalf of an agent, with full callback semantics.

        Same code path as the Claude agents' create_todo MCP tool (dependency
        wiring, autostart with the unmerged-creator auto-anchor, broadcasts).
        Used by out-of-process tool proxies (e.g. the Kimi board MCP server)
        via POST /api/items/{item_id}/agent-todos. ``options`` are the keyword
        options in ``TODO_OPTION_DEFAULTS``; any other keyword is a TypeError.
        """
        callback = self._create_on_create_todo_callback(creator_item_id)
        return await callback(
            title, description, **_todo_options(options, "BoardToolCallbacksMixin.create_agent_todo")
        )

    def _create_on_create_todo_callback(self, item_id: str):
        async def on_create_todo(title: str, description: str, **options) -> Dict[str, Any]:
            """Create the todo. ``options`` are the keywords in ``TODO_OPTION_DEFAULTS``."""
            opts = _todo_options(options, "on_create_todo")
            autostart = opts["autostart"]
            item = await self.db.create_todo_item(
                title, description, opts["epic_id"], autostart,
                auto_approve=self._coerce_auto_approve(opts["auto_approve"]),
                use_chrome=bool(opts["use_chrome"]),
            )
            effective_requires, auto_anchored = await self._effective_requires(
                item_id, item["id"], opts["requires"], autostart,
            )
            if effective_requires:
                await self.db.set_item_dependencies(item["id"], effective_requires)
            await self._announce_new_todo(item_id, item, title, auto_anchored)
            if effective_requires:
                await self._broadcast_blocked_status()
            if autostart and not effective_requires:
                self._schedule_autostart(item_id, item, title)
            return item
        return on_create_todo

    @staticmethod
    def _coerce_auto_approve(auto_approve: Any) -> int:
        """Coerce auto_approve to a known mode (0/1/2). Anything else falls back to OFF."""
        try:
            mode = int(auto_approve) if auto_approve is not None else 0
        except (TypeError, ValueError):
            mode = 0
        return mode if mode in AUTO_APPROVE_MODES else AUTO_APPROVE_OFF

    async def _effective_requires(self, creator_id: str, new_item_id: str,
                                  requires: Optional[list], autostart: bool) -> tuple[list, bool]:
        """The new todo's dependencies, and whether the creator was auto-added.

        Safe default for the empty-requires footgun: a task spawned by an
        in-flight agent must not start before the creating card's own work
        merges, or it branches off a `main` that doesn't have that work yet.
        When the agent asks for autostart but gives no deps, anchor the new
        task to the creating card so it waits for our merge. Only do this
        while the creator is still in flight (not yet merged) — if it's
        already done/archived its work is on main and immediate start is fine.
        """
        if requires:
            return list(requires), False
        if not autostart or new_item_id == creator_id:
            return [], False
        creator = await self.db.get_item(creator_id)
        if creator and creator.get("column_name") not in ("done", "archive"):
            return [creator_id], True
        return [], False

    async def _announce_new_todo(self, creator_id: str, item: Dict[str, Any], title: str,
                                 auto_anchored: bool) -> None:
        """Log the new todo on the creator's card and broadcast it."""
        await self._log_and_notify(creator_id, "system", f"Created todo item: {title}")
        if auto_anchored:
            await self._log_and_notify(
                creator_id, "system",
                f"'{title}' will wait for this card to merge before it starts "
                "(auto-added dependency to avoid branching off an unmerged main).",
            )
        await self.notifications.broadcast_item_created(item)

    async def _broadcast_blocked_status(self) -> None:
        blocked_status = await self.db.get_all_blocked_status()
        await self.notifications.ws_manager.broadcast("blocked_status_changed", {
            "blocked": blocked_status,
        })

    def _schedule_autostart(self, creator_id: str, item: Dict[str, Any], title: str) -> None:
        """Start the new todo's agent in the background; failures are logged on the creator."""
        async def _autostart_agent(new_item_id: str, new_title: str):
            try:
                await self.start_agent(new_item_id)
                await self._log_and_notify(creator_id, "system", f"Auto-started agent for: {new_title}")
            except Exception as e:
                logger.error(f"Autostart failed for item {new_item_id}: {e}")
                await self._log_and_notify(creator_id, "system", f"⚠️ Auto-start failed for '{new_title}': {e}")

        task = asyncio.create_task(_autostart_agent(item["id"], title))
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() and t.exception() else None)
        item["autostart_scheduled"] = True

    def _create_on_create_epic_callback(self, item_id: str):
        async def on_create_epic(title: str, color: str) -> Dict[str, Any]:
            epic = await self.epics.create(title, color)
            # Tell the caller the conventional path for this epic's shared plan
            # so the planner writes it where every task in the epic will look.
            plan_path = epic_plan_relpath(title)
            epic["plan_path"] = plan_path
            await self._log_and_notify(
                item_id, "system",
                f"Created epic: {title} — shared plan path: {plan_path}",
            )
            await self.notifications.broadcast_epic_created(epic)
            return epic
        return on_create_epic

    def _create_on_delete_todo_callback(self, item_id: str):
        async def on_delete_todo(target_id: str) -> str:
            # Only allow deleting items in the todo column
            target = await self.db.get_item(target_id)
            if not target:
                return f"Item '{target_id}' not found."
            if target["column_name"] != "todo":
                return f"Cannot delete item '{target['title']}' — it is in the '{target['column_name']}' column. Only todo items can be deleted."
            deleted = await self.db.delete_item_and_related(target_id)
            if deleted:
                await self._log_and_notify(item_id, "system", f"Deleted todo item: {deleted['title']}")
                await self.notifications.broadcast_item_deleted(target_id)
                return f"Deleted todo item: {deleted['title']}"
            return f"Failed to delete item '{target_id}'."
        return on_delete_todo

    def _create_on_set_commit_message_callback(self, item_id: str):
        async def on_set_commit_message(message: str) -> str:
            result = self.sessions.set_commit_message(item_id, message)
            await self._log_and_notify(item_id, "system", f"Commit message set: {message}")
            return result
        return on_set_commit_message

    def _create_on_create_shortcut_callback(self, item_id: str):
        async def on_create_shortcut(name: str, command: str) -> Dict[str, Any]:
            import uuid as _uuid
            shortcuts_path = self.data_dir / "shortcuts.json" if self.data_dir else None
            if not shortcuts_path:
                return {"error": "Shortcuts not available"}

            # Load existing shortcuts
            shortcuts = []
            if shortcuts_path.exists():
                try:
                    shortcuts = json.loads(shortcuts_path.read_text())
                except Exception:
                    pass

            # Create new shortcut
            sc = {"id": _uuid.uuid4().hex[:10], "name": name, "command": command}
            shortcuts.append(sc)
            shortcuts_path.write_text(json.dumps(shortcuts, indent=2))

            await self._log_and_notify(item_id, "system", f"Created shortcut: {name} → `{command}`")
            await self.notifications.ws_manager.broadcast("shortcut_created", sc)
            return sc
        return on_create_shortcut

    def _create_on_who_am_i_callback(self, item_id: str):
        """Callback backing the who_am_i tool — returns the agent's OWN item.

        Closes over the agent's item_id so the agent can fetch its own card
        (id, title, column, dependencies) without guessing from view_board.
        """
        async def on_who_am_i() -> Dict[str, Any]:
            if not item_id:
                return {"error": "Could not determine your board item."}
            item = await self.db.get_item(item_id)
            if not item:
                return {"error": f"Board item {item_id} not found."}
            deps = await self.db.get_item_dependencies(item_id)
            return {
                "id": item["id"],
                "title": item.get("title", ""),
                "description": item.get("description", ""),
                "column_name": item.get("column_name", ""),
                "status": item.get("status"),
                "epic_id": item.get("epic_id"),
                "auto_start": item.get("auto_start"),
                "auto_approve": item.get("auto_approve"),
                "dependencies": deps or [],
            }
        return on_who_am_i

    def _create_on_view_board_callback(self):
        async def on_view_board() -> str:
            from ..config import COLUMNS
            items = await self.db.get_all_items()
            epics = await self.epics.list_all()
            epic_map = {e["id"]: e["title"] for e in epics}
            dep_map = await self._dependency_map(items)

            # Group by column
            by_column: Dict[str, List[Dict[str, Any]]] = {}
            for item in items:
                by_column.setdefault(item["column_name"], []).append(item)

            lines = self._board_epic_lines(epics)
            for col in COLUMNS:
                lines += self._board_column_lines(col, by_column.get(col["id"], []), epic_map, dep_map)
            return "\n".join(lines)
        return on_view_board

    async def _dependency_map(self, items: List[Dict[str, Any]]) -> Dict[str, list]:
        """item_id -> its required items, for items that have any."""
        dep_map = {}
        for item in items:
            deps = await self.db.get_item_dependencies(item["id"])
            if deps:
                dep_map[item["id"]] = deps
        return dep_map

    @staticmethod
    def _board_epic_lines(epics: List[Dict[str, Any]]) -> List[str]:
        """The board view's "## Epics" section (none when there are no epics)."""
        if not epics:
            return []
        lines = ["## Epics"]
        for epic in epics:
            lines.append(f"- [{epic['id']}] {epic['title']} (color: {epic.get('color', 'blue')})")
        lines.append("")
        return lines

    @staticmethod
    def _board_column_lines(col: Dict[str, Any], col_items: List[Dict[str, Any]],
                            epic_map: Dict[str, str], dep_map: Dict[str, list]) -> List[str]:
        """One board column: heading, one line per item (or "(empty)"), blank line."""
        lines = [f"## {col['label']} ({len(col_items)})"]
        for item in col_items:
            status = f" [{item['status']}]" if item.get("status") else ""
            epic_text = f" [Epic: {epic_map.get(item.get('epic_id', ''), '')}]" if item.get('epic_id') else ""
            deps = dep_map.get(item["id"], [])
            dep_text = f" [requires: {', '.join(d['id'] for d in deps)}]" if deps else ""
            lines.append(f"- [{item['id']}] {item['title']}{status}{epic_text}{dep_text}")
        if not col_items:
            lines.append("  (empty)")
        lines.append("")
        return lines

    def _create_on_graph_query_callback(self):
        async def on_graph_query(question: str) -> str:
            if not self.graph_service:
                return "Knowledge graph is not available."
            result = await self.graph_service.query(question or "")
            if result.get("ok"):
                return result.get("answer") or "(no result)"
            return f"Graph query failed: {result.get('error') or 'unknown error'}"
        return on_graph_query
