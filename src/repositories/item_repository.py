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

from ..domain.item_state import Event, ItemState, from_columns, to_columns
from ..domain.item_state import transition as _apply_event

if TYPE_CHECKING:
    # Avoid runtime import of DatabaseService — that import path triggers
    # `services/__init__.py`, which imports workflow_service, which imports
    # this module. The type hint alone (under `from __future__ import
    # annotations`) keeps the cycle broken.
    from ..services.database_service import DatabaseService


# Whitelist of `items` columns the repo will accept on writes. Replaces
# the old ALLOWED_ITEM_COLUMNS in database_service.py — moved here as
# part of Phase 2.5: the repo is now the only writer of items, so the
# defense-in-depth check belongs at this boundary. Anything else that
# gets passed in is a programming error and should raise loudly.
_WRITABLE_ITEM_COLUMNS = {
    "title", "description", "column_name", "status", "position",
    "branch_name", "worktree_path", "session_id", "model",
    "base_branch", "base_commit", "done_at", "epic_id",
    "merge_commit", "auto_start", "commit_message",
    "has_file_changes",
}


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

    # ---- writes -------------------------------------------------------------

    async def transition(
        self, item_id: str, event: Event, **extra_fields: Any
    ) -> dict[str, Any]:
        """Apply a state-machine transition to the item and persist it.

        Reads the current encoding, runs it through the SM with `event`,
        and writes back the canonical (column_name, status) for the new
        state. Any non-state fields (session_id, worktree_path, branch_name,
        merge_commit, commit_message, has_file_changes, base_branch,
        base_commit) can be passed as extra_fields and are written in the
        same UPDATE.

        Raises:
            ItemNotFound:           item_id does not exist.
            UnknownStateEncoding:   item's current row has an unknown
                                    (column_name, status) — should be rare
                                    and is logged at startup by the audit.
            InvalidTransition:      `event` is not legal from the current
                                    state.
        """
        invalid = set(extra_fields) - _WRITABLE_ITEM_COLUMNS
        if invalid:
            raise ValueError(f"unknown item field(s): {sorted(invalid)}")
        item = await self.get_or_raise(item_id)
        current_state = from_columns(item["column_name"], item.get("status"))
        new_state = _apply_event(current_state, event)
        col, status = to_columns(new_state)
        return await self.db.update_item(
            item_id, column_name=col, status=status, **extra_fields
        )

    async def move_to_column(
        self, item_id: str, target_column: str, position: int
    ) -> dict[str, Any]:
        """User-driven drag-and-drop move to a target column.

        DnD is a deliberate user override — we don't route it through the
        SM (the user is asserting the target, not following a workflow
        event). But we DO normalize the encoding so the SM can read the
        result later without hitting an off-canon (column, status) pair:

        - Cross-column move: status is cleared so the result is the
          column's "neutral" encoding (canonical for every column except
          'doing', which lands at the ('doing', None) staging encoding —
          handled by the SM's fallback as BACKLOG).
        - Same-column move (just reorder): status preserved.

        Done/archive moves additionally clear worktree_path. position
        shifting in the target column is the caller's responsibility
        (use shift_positions before the move).
        """
        item = await self.get_or_raise(item_id)
        cross_column = item.get("column_name") != target_column
        fields: dict[str, Any] = {"column_name": target_column, "position": position}
        if cross_column:
            fields["status"] = None
        if target_column in ("done", "archive"):
            fields["worktree_path"] = None
        # Preserve done_at when moving to archive — DatabaseService.update_item
        # only auto-sets done_at for the "done" column; for archive we want to
        # keep whatever timestamp the item had (matching the prior raw-SQL
        # COALESCE behavior). If the item never had a done_at, treat the move
        # as a "completion" event for archive too.
        if target_column == "archive":
            from datetime import datetime, timezone
            fields["done_at"] = item.get("done_at") or datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S"
            )
        return await self.db.update_item(item_id, **fields)

    async def shift_positions(
        self, column_name: str, from_position: int, exclude_id: str
    ) -> None:
        """Shift positions in a column to make room for an inserted item.
        Items at or after `from_position` (excluding `exclude_id`) move
        down by 1. Used by move_to_column callers to keep position dense."""
        await self.db.shift_positions_in_column(column_name, from_position, exclude_id)

    async def update_fields(self, item_id: str, **fields: Any) -> dict[str, Any]:
        """Update non-state fields on an item without firing a transition.

        Use this for pure field writes (assigning a session_id mid-flight,
        attaching a worktree path before the state is moved, etc.). Passing
        column_name or status is forbidden — go through transition() instead.
        """
        if "column_name" in fields or "status" in fields:
            raise ValueError(
                "use ItemRepository.transition() to change column_name/status; "
                "update_fields is for non-state field writes only"
            )
        invalid = set(fields) - _WRITABLE_ITEM_COLUMNS
        if invalid:
            raise ValueError(f"unknown item field(s): {sorted(invalid)}")
        return await self.db.update_item(item_id, **fields)
