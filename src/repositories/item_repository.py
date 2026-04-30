"""Read-only repository for items.

Phase 2.1 of REFACTOR_PLAN.md. The goal of this class is to give callers
intent-named methods like `get_or_raise`, `list_running`, `list_in_state`
instead of column-string queries scattered across services. The store
implementation still lives in DatabaseService for now — this is a thin
facade. Phase 2.2 adds state-changing methods; Phase 2.5 deletes the
ALLOWED_ITEM_COLUMNS whitelist that callers no longer need.

Items are returned as plain dicts to match the existing call sites.
Pydantic conversion is a separate concern (Phase 3 / typed AgentConfig).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from ..domain.item_state import ItemState, to_columns

if TYPE_CHECKING:
    # Avoid runtime import of DatabaseService — that import path triggers
    # `services/__init__.py`, which imports workflow_service, which imports
    # this module. The type hint alone (under `from __future__ import
    # annotations`) keeps the cycle broken.
    from ..services.database_service import DatabaseService


class ItemNotFound(ValueError):
    """Raised by ItemRepository.get_or_raise when no row matches the id.

    Subclasses ValueError so existing call sites that already except
    ValueError keep working without modification.
    """

    def __init__(self, item_id: str):
        super().__init__(f"Item {item_id!r} not found")
        self.item_id = item_id


class ItemRepository:
    """Read-only operations on items. Writes land in Phase 2.2."""

    def __init__(self, db_service: "DatabaseService"):
        self.db = db_service

    async def get(self, item_id: str) -> Optional[dict[str, Any]]:
        """Return the item or None if it doesn't exist."""
        return await self.db.get_item(item_id)

    async def get_or_raise(self, item_id: str) -> dict[str, Any]:
        """Return the item or raise ItemNotFound. Use this when callers
        would otherwise raise ValueError on missing items — it removes a
        layer of `if not item: raise ...` boilerplate."""
        item = await self.db.get_item(item_id)
        if item is None:
            raise ItemNotFound(item_id)
        return item

    async def list_all(self) -> list[dict[str, Any]]:
        return await self.db.get_all_items()

    async def list_in_state(self, state: ItemState) -> list[dict[str, Any]]:
        """Return every item currently in the given ItemState. Translates
        through to_columns() so callers don't repeat the encoding."""
        col, status = to_columns(state)
        items = await self.db.get_all_items()
        return [i for i in items if i.get("column_name") == col and i.get("status") == status]

    async def list_running(self) -> list[dict[str, Any]]:
        return await self.list_in_state(ItemState.RUNNING)

    async def list_queued(self, limit: int = 1) -> list[dict[str, Any]]:
        """Return up to `limit` queued items, ordered by position (top first).
        Wraps DatabaseService.get_queued_items because that one query is
        position-ordered and we don't want to re-implement the ordering here."""
        return await self.db.get_queued_items(limit=limit)
