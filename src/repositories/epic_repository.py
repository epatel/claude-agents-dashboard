"""Repository for epics.

Mirrors ItemRepository but simpler — epics have no state machine,
just CRUD with a small column allowlist that lives here at the
boundary instead of in DatabaseService.

Returns plain dicts to match existing call sites; Pydantic conversion
is a separate concern.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from ..services.database_service import DatabaseService


# Mirror of the old ALLOWED_EPIC_COLUMNS in database_service.py.
# Moved here as part of Phase 2.6.
_WRITABLE_EPIC_COLUMNS = {"title", "color", "position"}


class EpicNotFound(ValueError):
    """Raised when an epic_id does not exist. Subclasses ValueError so
    existing `except ValueError` sites keep working unchanged."""

    def __init__(self, epic_id: str):
        super().__init__(f"Epic {epic_id!r} not found")
        self.epic_id = epic_id


class EpicRepository:
    """CRUD over epics."""

    def __init__(self, db_service: "DatabaseService"):
        self.db = db_service

    async def list_all(self) -> list[dict[str, Any]]:
        return await self.db.get_epics()

    async def get(self, epic_id: str) -> Optional[dict[str, Any]]:
        epics = await self.db.get_epics()
        for epic in epics:
            if epic["id"] == epic_id:
                return epic
        return None

    async def create(self, title: str, color: str) -> dict[str, Any]:
        return await self.db.create_epic(title, color)

    async def update(self, epic_id: str, **fields: Any) -> dict[str, Any]:
        """Update epic fields. Raises EpicNotFound on a missing id and
        ValueError on unknown fields."""
        invalid = set(fields) - _WRITABLE_EPIC_COLUMNS
        if invalid:
            raise ValueError(f"unknown epic field(s): {sorted(invalid)}")
        epic = await self.db.update_epic(epic_id, **fields)
        if epic is None:
            raise EpicNotFound(epic_id)
        return epic

    async def delete(self, epic_id: str) -> dict[str, Any]:
        """Delete the epic. Returns the deleted row. Raises EpicNotFound
        if the id was never present."""
        epic = await self.db.delete_epic(epic_id)
        if epic is None:
            raise EpicNotFound(epic_id)
        return epic
