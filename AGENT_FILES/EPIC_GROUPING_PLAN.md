# Epic Grouping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add epic grouping to organize board items into higher-level work streams, with a collapsible progress panel, Todo column grouping, board filtering, and inline epic creation.

**Architecture:** Epics are a separate DB entity (`epics` table) linked to items via `epic_id` FK. Backend provides CRUD routes + WebSocket broadcasts. Frontend adds a collapsible panel above the board, groups Todo items by epic, shows colored badges on cards, and supports filtering.

**Tech Stack:** Python/FastAPI, SQLite/aiosqlite, Vanilla JS, Jinja2, CSS

**Spec:** `AGENT_FILES/EPIC_GROUPING_DESIGN.md`

---

## File Structure

### New files
- `src/migrations/versions/010_add_epics.py` — migration for epics table + epic_id on items
- `tests/unit/test_epics.py` — epic CRUD and DB tests

### Modified files
- `src/constants.py` — add `EPIC_COLORS` preset palette
- `src/models.py` — add `EpicCreate`, `EpicUpdate` pydantic models; add `epic_id` to `ItemCreate`/`ItemUpdate`
- `src/services/database_service.py` — add epic CRUD methods
- `src/services/notification_service.py` — add epic broadcast methods
- `src/web/routes.py` — add epic CRUD endpoints, update create/update item to handle `epic_id`
- `src/templates/board.html` — add epic panel HTML, epic dropdown in item dialog
- `src/templates/partials/card.html` — add epic badge
- `src/static/js/board.js` — add epic panel rendering, Todo grouping, card badges, filtering
- `src/static/js/item-dialog.js` — add epic dropdown + inline create
- `src/static/js/app.js` — handle epic WebSocket events
- `src/static/css/board.css` — epic panel + todo grouping styles
- `src/static/css/theme.css` — epic color CSS variables for light/dark
- `src/agent/board_view.py` — include epic info in board view
- `src/agent/todo.py` — accept optional `epic_id` in create_todo

---

## Task 1: Migration — Create epics table and add epic_id to items

**Files:**
- Create: `src/migrations/versions/010_add_epics.py`
- Test: `tests/unit/test_epics.py`

- [ ] **Step 1: Write the migration file**

Create `src/migrations/versions/010_add_epics.py`:

```python
"""Add epics table and epic_id column to items.

Epics group board items into higher-level work streams.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite


class AddEpicsMigration(Migration):

    def __init__(self):
        super().__init__(
            version="010",
            description="Add epics table and epic_id to items"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS epics (
                id         TEXT PRIMARY KEY,
                title      TEXT NOT NULL,
                color      TEXT NOT NULL DEFAULT 'blue',
                position   INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            ALTER TABLE items
            ADD COLUMN epic_id TEXT DEFAULT NULL REFERENCES epics(id)
        """)

    async def down(self, db: aiosqlite.Connection) -> None:
        await db.execute("ALTER TABLE items DROP COLUMN epic_id")
        await db.execute("DROP TABLE IF EXISTS epics")
```

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_epics.py`:

```python
"""Tests for epic grouping feature."""

import pytest
import pytest_asyncio
from pathlib import Path
import tempfile

from src.database import Database


@pytest_asyncio.fixture
async def db():
    """Create a test database with all migrations applied."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        database = Database(db_path)
        await database.initialize()
        yield database


@pytest.mark.asyncio
async def test_epics_table_exists(db):
    """Test that the epics table was created by migration."""
    async with db.connect() as conn:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='epics'"
        )
        row = await cursor.fetchone()
    assert row is not None, "epics table should exist"


@pytest.mark.asyncio
async def test_items_has_epic_id_column(db):
    """Test that items table has epic_id column."""
    async with db.connect() as conn:
        cursor = await conn.execute("PRAGMA table_info(items)")
        columns = [row[1] for row in await cursor.fetchall()]
    assert "epic_id" in columns


@pytest.mark.asyncio
async def test_create_epic(db):
    """Test creating an epic."""
    async with db.connect() as conn:
        await conn.execute(
            "INSERT INTO epics (id, title, color, position) VALUES (?, ?, ?, ?)",
            ("epic-001", "Auth Rewrite", "blue", 0),
        )
        await conn.commit()
        cursor = await conn.execute("SELECT * FROM epics WHERE id = ?", ("epic-001",))
        row = dict(await cursor.fetchone())
    assert row["title"] == "Auth Rewrite"
    assert row["color"] == "blue"
    assert row["position"] == 0


@pytest.mark.asyncio
async def test_assign_item_to_epic(db):
    """Test assigning an item to an epic."""
    async with db.connect() as conn:
        await conn.execute(
            "INSERT INTO epics (id, title, color, position) VALUES (?, ?, ?, ?)",
            ("epic-001", "Auth Rewrite", "blue", 0),
        )
        await conn.execute(
            "INSERT INTO items (id, title, column_name, position, epic_id) VALUES (?, ?, ?, ?, ?)",
            ("item-001", "Fix login", "todo", 0, "epic-001"),
        )
        await conn.commit()
        cursor = await conn.execute("SELECT epic_id FROM items WHERE id = ?", ("item-001",))
        row = await cursor.fetchone()
    assert row[0] == "epic-001"


@pytest.mark.asyncio
async def test_delete_epic_nullifies_items(db):
    """Test that deleting an epic nullifies epic_id on related items."""
    async with db.connect() as conn:
        await conn.execute(
            "INSERT INTO epics (id, title, color, position) VALUES (?, ?, ?, ?)",
            ("epic-001", "Auth Rewrite", "blue", 0),
        )
        await conn.execute(
            "INSERT INTO items (id, title, column_name, position, epic_id) VALUES (?, ?, ?, ?, ?)",
            ("item-001", "Fix login", "todo", 0, "epic-001"),
        )
        await conn.commit()

        # Delete the epic and nullify references
        await conn.execute("UPDATE items SET epic_id = NULL WHERE epic_id = ?", ("epic-001",))
        await conn.execute("DELETE FROM epics WHERE id = ?", ("epic-001",))
        await conn.commit()

        cursor = await conn.execute("SELECT epic_id FROM items WHERE id = ?", ("item-001",))
        row = await cursor.fetchone()
    assert row[0] is None
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `./run-tests.sh tests/unit/test_epics.py -v`
Expected: All 5 tests PASS

- [ ] **Step 4: Commit**

```bash
git add src/migrations/versions/010_add_epics.py tests/unit/test_epics.py
git commit -m "feat: add epics migration and DB tests"
```

---

## Task 2: Constants and Pydantic models

**Files:**
- Modify: `src/constants.py:20` (after OPTIONAL_BUILTIN_TOOLS)
- Modify: `src/models.py:15` (after ItemCreate), `src/models.py:24` (after ItemUpdate)

- [ ] **Step 1: Add EPIC_COLORS to constants.py**

Append after line 20 (end of file) in `src/constants.py`:

```python

# Preset epic color palette — keys map to CSS variables
# Each has light and dark variants defined in theme.css
EPIC_COLORS = [
    {"key": "red", "label": "Red", "light": "#dc2626", "dark": "#f87171"},
    {"key": "orange", "label": "Orange", "light": "#ea580c", "dark": "#fb923c"},
    {"key": "amber", "label": "Amber", "light": "#d97706", "dark": "#fbbf24"},
    {"key": "green", "label": "Green", "light": "#16a34a", "dark": "#4ade80"},
    {"key": "teal", "label": "Teal", "light": "#0d9488", "dark": "#2dd4a1"},
    {"key": "blue", "label": "Blue", "light": "#2563eb", "dark": "#60a5fa"},
    {"key": "purple", "label": "Purple", "light": "#7c3aed", "dark": "#a78bfa"},
    {"key": "pink", "label": "Pink", "light": "#db2777", "dark": "#f472b6"},
]
```

- [ ] **Step 2: Add EpicCreate and EpicUpdate to models.py**

After `ItemCreate` class (line 15) in `src/models.py`, add:

```python

class EpicCreate(BaseModel):
    title: str
    color: str = "blue"


class EpicUpdate(BaseModel):
    title: Optional[str] = None
    color: Optional[str] = None
    position: Optional[int] = None
```

- [ ] **Step 3: Add epic_id to ItemCreate and ItemUpdate**

In `src/models.py`, add `epic_id: Optional[str] = None` to both `ItemCreate` (after `model` field) and `ItemUpdate` (after `model` field):

`ItemCreate` becomes:
```python
class ItemCreate(BaseModel):
    title: str
    description: str = ""
    model: Optional[str] = None
    epic_id: Optional[str] = None
```

`ItemUpdate` becomes:
```python
class ItemUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    column_name: Optional[str] = None
    position: Optional[int] = None
    status: Optional[str] = None
    model: Optional[str] = None
    epic_id: Optional[str] = None
```

- [ ] **Step 4: Run existing tests to verify no regressions**

Run: `./run-tests.sh -v`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add src/constants.py src/models.py
git commit -m "feat: add epic colors, pydantic models, and epic_id to items"
```

---

## Task 3: Database service — Epic CRUD methods

**Files:**
- Modify: `src/services/database_service.py:286` (append after last method)
- Test: `tests/unit/test_epics.py` (append new tests)

- [ ] **Step 1: Write failing tests for DB service methods**

Append to `tests/unit/test_epics.py`:

```python
from src.services.database_service import DatabaseService


@pytest_asyncio.fixture
async def db_service(db):
    """Create a DatabaseService instance."""
    return DatabaseService(db)


@pytest.mark.asyncio
async def test_db_service_create_epic(db_service):
    """Test creating an epic via DatabaseService."""
    epic = await db_service.create_epic("Auth Rewrite", "blue")
    assert epic["title"] == "Auth Rewrite"
    assert epic["color"] == "blue"
    assert "id" in epic


@pytest.mark.asyncio
async def test_db_service_get_epics(db_service):
    """Test listing all epics."""
    await db_service.create_epic("Epic A", "red")
    await db_service.create_epic("Epic B", "green")
    epics = await db_service.get_epics()
    assert len(epics) == 2
    assert epics[0]["title"] == "Epic A"
    assert epics[1]["title"] == "Epic B"


@pytest.mark.asyncio
async def test_db_service_update_epic(db_service):
    """Test updating an epic."""
    epic = await db_service.create_epic("Old Title", "blue")
    updated = await db_service.update_epic(epic["id"], title="New Title", color="red")
    assert updated["title"] == "New Title"
    assert updated["color"] == "red"


@pytest.mark.asyncio
async def test_db_service_delete_epic(db_service):
    """Test deleting an epic nullifies item epic_ids."""
    epic = await db_service.create_epic("Temp Epic", "blue")
    # Create an item assigned to this epic
    async with db_service.db.connect() as conn:
        await conn.execute(
            "INSERT INTO items (id, title, column_name, position, epic_id) VALUES (?, ?, ?, ?, ?)",
            ("item-del-1", "Test Item", "todo", 0, epic["id"]),
        )
        await conn.commit()

    deleted = await db_service.delete_epic(epic["id"])
    assert deleted["id"] == epic["id"]

    # Verify item's epic_id was nullified
    async with db_service.db.connect() as conn:
        cursor = await conn.execute("SELECT epic_id FROM items WHERE id = ?", ("item-del-1",))
        row = await cursor.fetchone()
    assert row[0] is None


@pytest.mark.asyncio
async def test_db_service_get_epic_progress(db_service):
    """Test getting epic progress stats."""
    epic = await db_service.create_epic("Progress Epic", "blue")
    async with db_service.db.connect() as conn:
        await conn.execute(
            "INSERT INTO items (id, title, column_name, position, epic_id) VALUES (?, ?, ?, ?, ?)",
            ("item-p1", "Todo Item", "todo", 0, epic["id"]),
        )
        await conn.execute(
            "INSERT INTO items (id, title, column_name, position, epic_id) VALUES (?, ?, ?, ?, ?)",
            ("item-p2", "Done Item", "done", 0, epic["id"]),
        )
        await conn.commit()

    progress = await db_service.get_epic_progress()
    assert epic["id"] in progress
    assert progress[epic["id"]]["todo"] == 1
    assert progress[epic["id"]]["done"] == 1
    assert progress[epic["id"]]["total"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./run-tests.sh tests/unit/test_epics.py -k "db_service" -v`
Expected: FAIL — methods don't exist yet

- [ ] **Step 3: Implement epic CRUD methods in DatabaseService**

Append at end of `DatabaseService` class in `src/services/database_service.py` (after line 286, before the file ends):

```python
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
            # Get next position
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
            epic = dict(row) if row else None

            await conn.execute("UPDATE items SET epic_id = NULL WHERE epic_id = ?", (epic_id,))
            await conn.execute("DELETE FROM epics WHERE id = ?", (epic_id,))
            await conn.commit()

        return epic

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
            progress[eid]["total"] += cnt
        return progress
```

Also add the import for `new_id` at the top of `database_service.py`. Find the existing imports and add:

```python
from ..models import new_id
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./run-tests.sh tests/unit/test_epics.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/services/database_service.py tests/unit/test_epics.py
git commit -m "feat: add epic CRUD methods to DatabaseService"
```

---

## Task 4: Notification service — Epic broadcasts

**Files:**
- Modify: `src/services/notification_service.py:44` (after broadcast_clarification_requested)

- [ ] **Step 1: Add epic broadcast methods**

After `broadcast_clarification_requested` method (line 44) in `src/services/notification_service.py`, add:

```python

    async def broadcast_epic_created(self, epic: Dict[str, Any]):
        """Broadcast epic creation event."""
        await self.ws_manager.broadcast("epic_created", epic)

    async def broadcast_epic_updated(self, epic: Dict[str, Any]):
        """Broadcast epic update event."""
        await self.ws_manager.broadcast("epic_updated", epic)

    async def broadcast_epic_deleted(self, epic_id: str):
        """Broadcast epic deletion event."""
        await self.ws_manager.broadcast("epic_deleted", {"id": epic_id})
```

- [ ] **Step 2: Commit**

```bash
git add src/services/notification_service.py
git commit -m "feat: add epic broadcast methods to NotificationService"
```

---

## Task 5: Backend routes — Epic CRUD endpoints

**Files:**
- Modify: `src/web/routes.py` — add imports, add epic endpoints before WebSocket section

- [ ] **Step 1: Update imports in routes.py**

In `src/web/routes.py`, update the models import (line 12):

Change:
```python
from ..models import ItemCreate, ItemUpdate, ItemMove, ClarificationResponse, AgentConfig, new_id
```
To:
```python
from ..models import ItemCreate, ItemUpdate, ItemMove, ClarificationResponse, AgentConfig, EpicCreate, EpicUpdate, new_id
```

Add constants import — update line 11:
```python
from ..config import COLUMNS
```
To:
```python
from ..config import COLUMNS
from ..constants import EPIC_COLORS
```

- [ ] **Step 2: Add epic CRUD routes**

Insert before the `# --- WebSocket ---` comment (line 777) in `src/web/routes.py`:

```python

# --- Epics ---

@router.get("/api/epics")
async def get_epics(request: Request):
    """Get all epics with progress stats."""
    db_service = request.app.state.orchestrator.db
    epics = await db_service.get_epics()
    progress = await db_service.get_epic_progress()
    for epic in epics:
        epic["progress"] = progress.get(epic["id"], {
            "todo": 0, "doing": 0, "questions": 0, "review": 0, "done": 0, "archive": 0, "total": 0
        })
    return epics


@router.get("/api/epics/colors")
async def get_epic_colors():
    """Get the preset epic color palette."""
    return EPIC_COLORS


@router.post("/api/epics")
async def create_epic(request: Request, body: EpicCreate):
    """Create a new epic."""
    db_service = request.app.state.orchestrator.db
    ns = request.app.state.orchestrator.notifications
    epic = await db_service.create_epic(body.title, body.color)
    await ns.broadcast_epic_created(epic)
    _invalidate_stats_cache()
    return epic


@router.put("/api/epics/{epic_id}")
async def update_epic(request: Request, epic_id: str, body: EpicUpdate):
    """Update an epic."""
    db_service = request.app.state.orchestrator.db
    ns = request.app.state.orchestrator.notifications
    kwargs = body.model_dump(exclude_unset=True)
    epic = await db_service.update_epic(epic_id, **kwargs)
    if not epic:
        raise HTTPException(status_code=404, detail="Epic not found")
    await ns.broadcast_epic_updated(epic)
    return epic


@router.delete("/api/epics/{epic_id}")
async def delete_epic(request: Request, epic_id: str):
    """Delete an epic (nullifies epic_id on related items)."""
    db_service = request.app.state.orchestrator.db
    ns = request.app.state.orchestrator.notifications
    epic = await db_service.delete_epic(epic_id)
    if not epic:
        raise HTTPException(status_code=404, detail="Epic not found")
    await ns.broadcast_epic_deleted(epic_id)
    _invalidate_stats_cache()
    return {"success": True}
```

- [ ] **Step 3: Update create_item to handle epic_id**

In the `create_item` endpoint (line 228-251), update the INSERT to include `epic_id`. Change line 240-242:

From:
```python
        await conn.execute(
            "INSERT INTO items (id, title, description, column_name, position, model) VALUES (?, ?, ?, 'todo', ?, ?)",
            (item_id, body.title, body.description, position, body.model),
        )
```

To:
```python
        await conn.execute(
            "INSERT INTO items (id, title, description, column_name, position, model, epic_id) VALUES (?, ?, ?, 'todo', ?, ?, ?)",
            (item_id, body.title, body.description, position, body.model, body.epic_id),
        )
```

- [ ] **Step 4: Run all tests**

Run: `./run-tests.sh -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/web/routes.py
git commit -m "feat: add epic CRUD routes and epic_id to item creation"
```

---

## Task 6: CSS — Epic colors, panel, and Todo grouping styles

**Files:**
- Modify: `src/static/css/theme.css` (add epic color variables)
- Modify: `src/static/css/board.css` (add epic panel + todo grouping styles)

- [ ] **Step 1: Add epic color CSS variables to theme.css**

At the end of the `:root, [data-theme="light"]` block in `src/static/css/theme.css`, add epic color variables. At the end of the `[data-theme="dark"]` block, add the dark variants.

Append inside the light theme block (before its closing `}`):

```css
    /* Epic colors */
    --epic-red: #dc2626;
    --epic-orange: #ea580c;
    --epic-amber: #d97706;
    --epic-green: #16a34a;
    --epic-teal: #0d9488;
    --epic-blue: #2563eb;
    --epic-purple: #7c3aed;
    --epic-pink: #db2777;
```

Append inside the dark theme block (before its closing `}`):

```css
    /* Epic colors */
    --epic-red: #f87171;
    --epic-orange: #fb923c;
    --epic-amber: #fbbf24;
    --epic-green: #4ade80;
    --epic-teal: #2dd4a1;
    --epic-blue: #60a5fa;
    --epic-purple: #a78bfa;
    --epic-pink: #f472b6;
```

- [ ] **Step 2: Add epic panel and todo grouping styles to board.css**

Append to end of `src/static/css/board.css`:

```css

/* --- Epic panel --- */

.epic-panel-toggle {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 12px;
    cursor: pointer;
    color: var(--text-secondary);
    font-size: 13px;
    user-select: none;
}
.epic-panel-toggle:hover { color: var(--text-primary); }
.epic-panel-toggle svg { transition: transform 0.15s; }
.epic-panel-toggle.expanded svg { transform: rotate(90deg); }

.epic-panel {
    display: none;
    padding: 8px 20px 12px;
    gap: 10px;
    flex-wrap: wrap;
    align-items: center;
    border-bottom: 1px solid var(--border-light);
}
.epic-panel.visible { display: flex; }

.epic-card {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 12px;
    background: var(--bg-secondary);
    border: 1px solid var(--border-light);
    border-radius: var(--radius-sm);
    cursor: pointer;
    font-size: 13px;
    transition: border-color 0.15s;
    min-width: 140px;
}
.epic-card:hover { border-color: var(--accent); }
.epic-card.active {
    border-color: var(--accent);
    box-shadow: 0 0 0 1px var(--accent);
}

.epic-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    flex-shrink: 0;
}

.epic-card-title {
    flex: 1;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.epic-progress-bar {
    width: 60px;
    height: 4px;
    background: var(--border-light);
    border-radius: 2px;
    overflow: hidden;
    flex-shrink: 0;
}
.epic-progress-fill {
    height: 100%;
    border-radius: 2px;
    transition: width 0.3s;
}

.epic-progress-count {
    font-size: 11px;
    color: var(--text-muted);
    white-space: nowrap;
}

.epic-filter-clear {
    font-size: 12px;
    color: var(--accent);
    cursor: pointer;
    padding: 4px 8px;
    border: 1px solid var(--accent);
    border-radius: var(--radius-sm);
    background: none;
}
.epic-filter-clear:hover {
    background: var(--accent);
    color: white;
}

/* --- Epic badge on cards --- */

.card-epic-badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 11px;
    color: var(--text-secondary);
    margin-bottom: 4px;
}
.card-epic-badge .epic-dot {
    width: 8px;
    height: 8px;
}

/* --- Todo column epic grouping --- */

.todo-epic-group { margin-bottom: 8px; }

.todo-epic-header {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 8px;
    font-size: 12px;
    font-weight: 500;
    color: var(--text-secondary);
    cursor: pointer;
    user-select: none;
    border-radius: var(--radius-sm);
}
.todo-epic-header:hover { background: var(--bg-hover); }

.todo-epic-header svg { transition: transform 0.15s; }
.todo-epic-header.expanded svg { transform: rotate(90deg); }

.todo-epic-count {
    font-size: 11px;
    color: var(--text-muted);
    margin-left: auto;
}

/* --- Epic dropdown in item dialog --- */

.epic-color-swatches {
    display: flex;
    gap: 6px;
    margin-top: 6px;
}
.epic-color-swatch {
    width: 24px;
    height: 24px;
    border-radius: 50%;
    border: 2px solid transparent;
    cursor: pointer;
    transition: border-color 0.15s;
}
.epic-color-swatch:hover { border-color: var(--text-secondary); }
.epic-color-swatch.selected { border-color: var(--accent); }

.epic-inline-create {
    display: none;
    padding: 8px;
    margin-top: 4px;
    border: 1px solid var(--border-light);
    border-radius: var(--radius-sm);
    background: var(--bg-hover);
}
.epic-inline-create.visible { display: block; }
```

- [ ] **Step 3: Commit**

```bash
git add src/static/css/theme.css src/static/css/board.css
git commit -m "feat: add epic CSS — panel, badges, todo grouping, color variables"
```

---

## Task 7: HTML template — Epic panel and item dialog dropdown

**Files:**
- Modify: `src/templates/board.html:4` (add epic panel before board)
- Modify: `src/templates/board.html:60-68` (add epic dropdown in item dialog)
- Modify: `src/templates/partials/card.html:9` (add epic badge)

- [ ] **Step 1: Add epic panel above the board**

In `src/templates/board.html`, insert before line 4 (`<main class="board">`):

```html
<div class="epic-panel-toggle" onclick="Board.toggleEpicPanel()">
    <svg class="epic-panel-chevron" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 4 10 8 6 12"/></svg>
    Epics
</div>
<div class="epic-panel" id="epic-panel"></div>
```

- [ ] **Step 2: Add epic dropdown to item dialog**

In `src/templates/board.html`, insert after the model `</select>` closing `</div>` (after line 68, the closing `</div>` of the model form-group) and before the Attachments form-group:

```html
            <div class="form-group">
                <label for="item-form-epic">Epic <span class="tooltip" data-tip="Assign this item to an epic to group related tasks together.">?</span></label>
                <select id="item-form-epic">
                    <option value="">No Epic</option>
                </select>
                <button type="button" class="btn btn-xs" style="margin-top: 4px;" onclick="ItemDialog.showInlineEpicCreate()">+ New Epic</button>
                <div id="epic-inline-create" class="epic-inline-create">
                    <input type="text" id="epic-create-title" placeholder="Epic name" style="margin-bottom: 6px; width: 100%;">
                    <div class="epic-color-swatches" id="epic-color-swatches"></div>
                    <div style="margin-top: 8px; display: flex; gap: 6px;">
                        <button type="button" class="btn btn-xs btn-primary" onclick="ItemDialog.createEpicInline()">Create</button>
                        <button type="button" class="btn btn-xs" onclick="ItemDialog.hideInlineEpicCreate()">Cancel</button>
                    </div>
                </div>
            </div>
```

- [ ] **Step 3: Add epic badge to card partial**

In `src/templates/partials/card.html`, insert after line 8 (the `onclick` line) and before line 9 (`<div class="card-title">`):

```html
    {% if item.epic_title %}
    <div class="card-epic-badge">
        <span class="epic-dot" style="background: var(--epic-{{ item.epic_color or 'blue' }})"></span>
        {{ item.epic_title }}
    </div>
    {% endif %}
```

Note: `epic_title` and `epic_color` will be joined from the epics table in the route that renders the board. This requires a small update to the board rendering query (see Task 8).

- [ ] **Step 4: Commit**

```bash
git add src/templates/board.html src/templates/partials/card.html
git commit -m "feat: add epic panel, dropdown, and card badge HTML templates"
```

---

## Task 8: Board route — Join epic data for server-rendered cards

**Files:**
- Modify: `src/web/routes.py` — update the board rendering route to join epic data

- [ ] **Step 1: Find and update the board rendering route**

Find the route that renders the board template (serves HTML). It queries items and passes them to the template. Update the items query to LEFT JOIN with epics to include `epic_title` and `epic_color`.

Look for the route that does `SELECT * FROM items` and renders `board.html`. Update the query:

Change:
```python
cursor = await conn.execute("SELECT * FROM items")
```

To:
```python
cursor = await conn.execute(
    "SELECT items.*, epics.title as epic_title, epics.color as epic_color "
    "FROM items LEFT JOIN epics ON items.epic_id = epics.id"
)
```

- [ ] **Step 2: Run tests**

Run: `./run-tests.sh -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add src/web/routes.py
git commit -m "feat: join epic data for server-rendered board cards"
```

---

## Task 9: JavaScript — Epic panel rendering and board filtering

**Files:**
- Modify: `src/static/js/board.js` — add epic panel, filtering, todo grouping, card badges

- [ ] **Step 1: Add epic state and panel methods to Board object**

At the top of the `Board` object in `src/static/js/board.js` (after line 6, `_collapsedArchiveGroups: {}`), add:

```javascript
    // Epic state
    _epics: [],
    _epicFilter: null,  // currently filtered epic_id or null
    _epicPanelExpanded: localStorage.getItem('epicPanelExpanded') === 'true',
    _collapsedTodoEpicGroups: {},
```

- [ ] **Step 2: Add epic panel toggle and rendering**

After the `_isTodayGroup` method (after line 406) in `src/static/js/board.js`, add:

```javascript
    toggleEpicPanel() {
        this._epicPanelExpanded = !this._epicPanelExpanded;
        localStorage.setItem('epicPanelExpanded', this._epicPanelExpanded);
        this._renderEpicPanel();
    },

    async loadEpics() {
        try {
            this._epics = await Api.request('GET', '/api/epics');
        } catch (e) {
            console.error('Failed to load epics:', e);
            this._epics = [];
        }
        this._renderEpicPanel();
    },

    _renderEpicPanel() {
        const toggle = document.querySelector('.epic-panel-toggle');
        const panel = document.getElementById('epic-panel');
        if (!toggle || !panel) return;

        if (this._epicPanelExpanded) {
            toggle.classList.add('expanded');
            panel.classList.add('visible');
        } else {
            toggle.classList.remove('expanded');
            panel.classList.remove('visible');
            return;
        }

        let html = '';
        for (const epic of this._epics) {
            const p = epic.progress || {};
            const done = (p.done || 0);
            const total = (p.total || 0);
            const pct = total > 0 ? Math.round((done / total) * 100) : 0;
            const isActive = this._epicFilter === epic.id;
            html += `
                <div class="epic-card${isActive ? ' active' : ''}" onclick="Board.filterByEpic('${epic.id}')">
                    <span class="epic-dot" style="background: var(--epic-${epic.color})"></span>
                    <span class="epic-card-title">${Board.escapeHtml(epic.title)}</span>
                    <div class="epic-progress-bar">
                        <div class="epic-progress-fill" style="width: ${pct}%; background: var(--epic-${epic.color})"></div>
                    </div>
                    <span class="epic-progress-count">${done}/${total}</span>
                </div>
            `;
        }

        if (this._epicFilter) {
            html += `<button class="epic-filter-clear" onclick="Board.clearEpicFilter()">Clear filter</button>`;
        }

        panel.innerHTML = html;
    },

    filterByEpic(epicId) {
        if (this._epicFilter === epicId) {
            this.clearEpicFilter();
            return;
        }
        this._epicFilter = epicId;
        this._renderEpicPanel();
        this._applyEpicFilter();
    },

    clearEpicFilter() {
        this._epicFilter = null;
        this._renderEpicPanel();
        this._applyEpicFilter();
    },

    _applyEpicFilter() {
        // Show/hide cards based on epic filter
        const allCards = document.querySelectorAll('.card');
        for (const card of allCards) {
            const itemId = card.dataset.id;
            const item = this.items[itemId];
            if (!this._epicFilter || (item && item.epic_id === this._epicFilter)) {
                card.style.display = '';
            } else {
                card.style.display = 'none';
            }
        }
        // Re-render todo column (grouping changes when filtered)
        this.renderTodoColumn();
        // Re-render done/archive (filtering applies)
        this.renderDoneColumn();
        this.renderArchiveColumn();
        this.updateCounts();
    },
```

- [ ] **Step 3: Add Todo column epic grouping**

After the `_applyEpicFilter` method, add:

```javascript
    renderTodoColumn() {
        const col = document.querySelector('.column-cards[data-column="todo"]');
        if (!col) return;

        const todoItems = Object.values(this.items).filter(i => i.column_name === 'todo');

        // Apply epic filter
        const filtered = this._epicFilter
            ? todoItems.filter(i => i.epic_id === this._epicFilter)
            : todoItems;

        // If filtered or no epics, render flat
        if (this._epicFilter || this._epics.length === 0) {
            col.innerHTML = '';
            filtered.sort((a, b) => (a.position || 0) - (b.position || 0));
            for (const item of filtered) {
                col.appendChild(this.renderCard(item));
            }
            return;
        }

        // Group by epic
        const epicGroups = {};
        const noEpic = [];
        for (const item of filtered) {
            if (item.epic_id) {
                if (!epicGroups[item.epic_id]) epicGroups[item.epic_id] = [];
                epicGroups[item.epic_id].push(item);
            } else {
                noEpic.push(item);
            }
        }

        col.innerHTML = '';

        // Render epic groups in epic position order
        for (const epic of this._epics) {
            const items = epicGroups[epic.id];
            if (!items || items.length === 0) continue;

            const isCollapsed = this._collapsedTodoEpicGroups[epic.id] || false;

            const group = document.createElement('div');
            group.className = 'todo-epic-group';

            const header = document.createElement('div');
            header.className = 'todo-epic-header' + (isCollapsed ? '' : ' expanded');
            header.innerHTML = `
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 4 10 8 6 12"/></svg>
                <span class="epic-dot" style="background: var(--epic-${epic.color})"></span>
                ${Board.escapeHtml(epic.title)}
                <span class="todo-epic-count">${items.length}</span>
            `;
            header.addEventListener('click', () => {
                this._collapsedTodoEpicGroups[epic.id] = !isCollapsed;
                this.renderTodoColumn();
            });
            group.appendChild(header);

            if (!isCollapsed) {
                items.sort((a, b) => (a.position || 0) - (b.position || 0));
                for (const item of items) {
                    group.appendChild(this.renderCard(item));
                }
            }

            col.appendChild(group);
        }

        // "No Epic" group at the bottom
        if (noEpic.length > 0) {
            const group = document.createElement('div');
            group.className = 'todo-epic-group';
            const header = document.createElement('div');
            header.className = 'todo-epic-header expanded';
            header.innerHTML = `
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 4 10 8 6 12"/></svg>
                No Epic
                <span class="todo-epic-count">${noEpic.length}</span>
            `;
            header.addEventListener('click', () => {
                this._collapsedTodoEpicGroups['__none__'] = !this._collapsedTodoEpicGroups['__none__'];
                this.renderTodoColumn();
            });
            group.appendChild(header);

            if (!this._collapsedTodoEpicGroups['__none__']) {
                noEpic.sort((a, b) => (a.position || 0) - (b.position || 0));
                for (const item of noEpic) {
                    group.appendChild(this.renderCard(item));
                }
            }
            col.appendChild(group);
        }
    },
```

- [ ] **Step 4: Add epic badge to renderCard**

In the `renderCard` method in `src/static/js/board.js`, after line 316 (`div.onclick = () => Dialogs.showDetail(item.id);`) and before the `let statusHtml = '';` line, add:

```javascript
        // Epic badge
        let epicBadgeHtml = '';
        if (item.epic_id && !this._epicFilter) {
            const epic = this._epics.find(e => e.id === item.epic_id);
            if (epic) {
                epicBadgeHtml = `<div class="card-epic-badge"><span class="epic-dot" style="background: var(--epic-${epic.color})"></span>${this.escapeHtml(epic.title)}</div>`;
            }
        }
```

Then update the `div.innerHTML` template (line 370-378) to include `${epicBadgeHtml}` before the card-title:

```javascript
        div.innerHTML = `
            ${epicBadgeHtml}
            <div class="card-title">${this.escapeHtml(item.title)}</div>
            ${statusHtml}
            <div class="card-bottom">
                <div class="card-actions">${actionsHtml}</div>
                ${timestampHtml}
                ${logCountHtml}
            </div>
        `;
```

- [ ] **Step 5: Update init to load epics and render todo column**

Update `Board.init()` (line 8-15) to also load epics and use the new renderTodoColumn:

```javascript
    async init(initialItems) {
        for (const item of initialItems) {
            this.items[item.id] = item;
        }
        await this.loadEpics();
        this.renderTodoColumn();
        this.renderDoneColumn();
        this.renderArchiveColumn();
        this.updateCounts();
    },
```

- [ ] **Step 6: Update updateCard to handle todo column via renderTodoColumn**

In `updateCard` (line 545), add todo column to the special rendering path. After the done/archive check (line 558):

```javascript
        // Todo column uses grouped rendering
        if (item.column_name === 'todo') {
            if (prev && prev.column_name !== 'todo') {
                // Item moved away from another column, re-render that column
            }
            this.renderTodoColumn();
            this.updateCounts();
            return;
        }
```

Also, when an item moves OUT of todo (already handled by the existing code removing the old card), ensure renderTodoColumn is called:

```javascript
        if (prev && prev.column_name === 'todo' && item.column_name !== 'todo') {
            this.renderTodoColumn();
        }
```

- [ ] **Step 7: Update updateCounts for filtered state**

In `updateCounts` (line 605), update the todo count to use items cache like done:

```javascript
    updateCounts() {
        document.querySelectorAll('.column').forEach(col => {
            const colName = col.dataset.column;
            let count;
            if (colName === 'done' || colName === 'todo') {
                const items = Object.values(this.items).filter(i => i.column_name === colName);
                count = this._epicFilter
                    ? items.filter(i => i.epic_id === this._epicFilter).length
                    : items.length;
            } else {
                count = col.querySelectorAll('.card:not([style*="display: none"])').length;
            }
            const badge = col.querySelector('.column-count');
            if (badge) badge.textContent = count;
        });
    },
```

- [ ] **Step 8: Commit**

```bash
git add src/static/js/board.js
git commit -m "feat: add epic panel, filtering, todo grouping, and card badges in board.js"
```

---

## Task 10: JavaScript — Item dialog epic dropdown and inline create

**Files:**
- Modify: `src/static/js/item-dialog.js`

- [ ] **Step 1: Add epic dropdown population**

Add these methods to the `ItemDialog` object in `src/static/js/item-dialog.js` (before the closing `};`):

```javascript
    async _populateEpicDropdown(selectedEpicId) {
        const select = document.getElementById('item-form-epic');
        if (!select) return;

        try {
            const epics = await Api.request('GET', '/api/epics');
            select.innerHTML = '<option value="">No Epic</option>';
            for (const epic of epics) {
                const opt = document.createElement('option');
                opt.value = epic.id;
                opt.textContent = epic.title;
                opt.style.color = `var(--epic-${epic.color})`;
                if (epic.id === selectedEpicId) opt.selected = true;
                select.appendChild(opt);
            }
        } catch (e) {
            console.error('Failed to load epics:', e);
        }
    },

    showInlineEpicCreate() {
        const container = document.getElementById('epic-inline-create');
        if (!container) return;
        container.classList.add('visible');
        document.getElementById('epic-create-title').value = '';
        this._selectedEpicColor = 'blue';
        this._renderColorSwatches();
        document.getElementById('epic-create-title').focus();
    },

    hideInlineEpicCreate() {
        const container = document.getElementById('epic-inline-create');
        if (container) container.classList.remove('visible');
    },

    _renderColorSwatches() {
        const container = document.getElementById('epic-color-swatches');
        if (!container) return;
        const colors = ['red', 'orange', 'amber', 'green', 'teal', 'blue', 'purple', 'pink'];
        container.innerHTML = colors.map(c =>
            `<div class="epic-color-swatch${c === this._selectedEpicColor ? ' selected' : ''}"
                  style="background: var(--epic-${c})"
                  onclick="ItemDialog._selectEpicColor('${c}')"></div>`
        ).join('');
    },

    _selectEpicColor(color) {
        this._selectedEpicColor = color;
        this._renderColorSwatches();
    },

    async createEpicInline() {
        const title = document.getElementById('epic-create-title').value.trim();
        if (!title) return;

        try {
            const epic = await Api.request('POST', '/api/epics', {
                title,
                color: this._selectedEpicColor || 'blue',
            });
            this.hideInlineEpicCreate();
            await this._populateEpicDropdown(epic.id);
            // Also refresh board's epic list
            Board.loadEpics();
        } catch (e) {
            console.error('Failed to create epic:', e);
        }
    },

    _selectedEpicColor: 'blue',
```

- [ ] **Step 2: Update openNewItem and openEditItem to populate epic dropdown**

In `openNewItem()` (line 8), add after line 13 (`document.getElementById('item-form-model').value = '';`):

```javascript
        document.getElementById('item-form-epic').value = '';
        this.hideInlineEpicCreate();
        await this._populateEpicDropdown(null);
```

In `openEditItem()` (line 24), add after line 29 (`document.getElementById('item-form-model').value = item.model || '';`):

```javascript
        document.getElementById('item-form-epic').value = item.epic_id || '';
        this.hideInlineEpicCreate();
        await this._populateEpicDropdown(item.epic_id);
```

- [ ] **Step 3: Update submitItem and submitItemAndStart to send epic_id**

In `submitItem()` (line 96), after line 101 (`const model = ...`), add:

```javascript
        const epic_id = document.getElementById('item-form-epic').value || null;
```

Update the `createItem` call (line 112) to include epic_id:

```javascript
                const item = await Api.createItem(title, description, model, epic_id);
```

Update the `updateItem` call (line 110) to include epic_id:

```javascript
                const updateData = { title, description, epic_id };
```

Do the same changes in `submitItemAndStart()` (line 133): add epic_id extraction and pass it to createItem/updateItem.

- [ ] **Step 4: Update Api.createItem to accept epic_id**

In `src/static/js/api.js`, find the `createItem` method and add the `epic_id` parameter:

```javascript
    async createItem(title, description, model, epic_id) {
        return this.request('POST', '/api/items', { title, description, model, epic_id });
    },
```

- [ ] **Step 5: Commit**

```bash
git add src/static/js/item-dialog.js src/static/js/api.js
git commit -m "feat: add epic dropdown and inline create to item dialog"
```

---

## Task 11: JavaScript — WebSocket event handling for epics

**Files:**
- Modify: `src/static/js/app.js:319` (handleEvent switch)

- [ ] **Step 1: Add epic event cases to handleEvent**

In `src/static/js/app.js`, in the `handleEvent` method (line 319), add cases before the `default:` (line 373):

```javascript
            case 'epic_created':
            case 'epic_updated':
            case 'epic_deleted':
                Board.loadEpics();
                // Reload items in case epic assignments changed
                if (type === 'epic_deleted') {
                    Board.loadAndRender();
                }
                break;
```

- [ ] **Step 2: Update Board.init call in app.js**

Find where `Board.init(initialItems)` is called in app.js. Since `Board.init` is now async, update the call to use `await`:

```javascript
await Board.init(initialItems);
```

Or if it's in a non-async context, chain with `.then()`.

- [ ] **Step 3: Commit**

```bash
git add src/static/js/app.js
git commit -m "feat: handle epic WebSocket events in app.js"
```

---

## Task 12: Agent integration — Update board_view and create_todo MCP tools

**Files:**
- Modify: `src/agent/board_view.py`
- Modify: `src/agent/todo.py`

- [ ] **Step 1: Update board_view callback to include epic info**

The `board_view.py` tool itself doesn't need changes — the formatting happens in the callback. Find where the `on_view_board` callback is defined (in `workflow_service.py` or `session_service.py`) and update the board text formatting to include epic name per item.

In the callback, when formatting each item, add:

```python
epic_text = f" [Epic: {item.get('epic_title', '')}]" if item.get('epic_id') else ""
line = f"  - {item['title']}{epic_text} (ID: {item['id']})"
```

- [ ] **Step 2: Update create_todo schema to accept epic_id**

In `src/agent/todo.py`, update `CREATE_TODO_SCHEMA` (line 9):

```python
CREATE_TODO_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "The title of the todo item. Should be clear and concise.",
        },
        "description": {
            "type": "string",
            "description": "Optional detailed description of the todo item.",
        },
        "epic_id": {
            "type": "string",
            "description": "Optional epic ID to assign this todo to. Use view_board to see available epics.",
        },
    },
    "required": ["title"],
}
```

Update the `create_todo` function (line 56-60) to pass `epic_id`:

```python
    async def create_todo(input: dict) -> dict:
        """Create a new todo item."""
        title = input.get("title", "")
        description = input.get("description", "")
        epic_id = input.get("epic_id")
        item_info = await on_create_todo(title, description, epic_id)
```

Update the callback signature in the docstring (line 40):

```python
        on_create_todo: async callback(title, description, epic_id=None) -> dict
```

Then update the corresponding callback in workflow_service.py to accept and pass `epic_id` to `create_todo_item`.

- [ ] **Step 3: Update DatabaseService.create_todo_item to accept epic_id**

In `src/services/database_service.py`, update the `create_todo_item` method signature and INSERT:

```python
    async def create_todo_item(self, title: str, description: str, epic_id: str = None) -> Dict[str, Any]:
```

Update the INSERT statement:

```python
            await conn.execute(
                "INSERT INTO items (id, title, description, column_name, position, epic_id) VALUES (?, ?, ?, 'todo', ?, ?)",
                (todo_id, title, description, position, epic_id),
            )
```

- [ ] **Step 4: Run all tests**

Run: `./run-tests.sh -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent/board_view.py src/agent/todo.py src/services/database_service.py
git commit -m "feat: add epic support to board_view and create_todo MCP tools"
```

---

## Task 13: Update CLAUDE.md documentation

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update relevant sections**

Add epics to:
- Database section: mention `epics` table and `epic_id` FK on items
- Migration list: add `010_add_epics.py`
- Key design decisions: add bullet about epic grouping
- Frontend modules: mention epic panel in board.js
- ER diagram: add `epics` entity

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for epic grouping feature"
```

---

## Task 14: Final integration test

- [ ] **Step 1: Run the full test suite**

Run: `./run-tests.sh -v`
Expected: All tests PASS (including the new epic tests)

- [ ] **Step 2: Manual smoke test**

Start the server and verify:
1. Epic panel appears above the board (collapsed by default)
2. Can expand the panel
3. Can create an epic via the item dialog
4. New item can be assigned to an epic
5. Todo column groups items by epic
6. Clicking an epic in the panel filters the board
7. Cards show epic color badges
8. Deleting an epic removes the badge from items
9. Dark mode colors work correctly

- [ ] **Step 3: Run existing test suite to confirm no regressions**

Run: `./run-tests.sh -v`
Expected: All existing + new tests PASS
