# Epic Grouping Design

## Overview

Add epic grouping to organize board items into higher-level work streams. Epics are a separate entity (not items) with CRUD management, visual grouping in the Todo column, a collapsible progress panel above the board, and board filtering.

## Data Model

### New `epics` table

| Column     | Type    | Notes                          |
|------------|---------|--------------------------------|
| id         | text PK | UUID                           |
| title      | text    | Required                       |
| color      | text    | Key from preset palette        |
| position   | integer | For ordering in panel/dropdown |
| created_at | text    | ISO 8601 UTC                   |

### `items` table change

Add nullable `epic_id` text column (FK to `epics.id`).

### Migration

`010_add_epics.py` — creates `epics` table and adds `epic_id` column to `items`.

## Preset Color Palette

8 colors that work in both light and dark themes:

| Key    | Light hex | Dark hex  |
|--------|-----------|-----------|
| red    | #dc2626   | #f87171   |
| orange | #ea580c   | #fb923c   |
| amber  | #d97706   | #fbbf24   |
| green  | #16a34a   | #4ade80   |
| teal   | #0d9488   | #2dd4a1   |
| blue   | #2563eb   | #60a5fa   |
| purple | #7c3aed   | #a78bfa   |
| pink   | #db2777   | #f472b6   |

Defined in `constants.py` as `EPIC_COLORS`.

## Backend

### Routes

| Method | Path                  | Description                              |
|--------|-----------------------|------------------------------------------|
| GET    | /api/epics            | List all epics with progress stats       |
| POST   | /api/epics            | Create epic (title, color)               |
| PUT    | /api/epics/{id}       | Update epic (title, color, position)     |
| DELETE | /api/epics/{id}       | Delete epic (nullifies items' epic_id)   |

### `GET /api/epics` response shape

```json
[
  {
    "id": "uuid",
    "title": "Auth Rewrite",
    "color": "blue",
    "position": 0,
    "created_at": "2026-04-02T12:00:00Z",
    "progress": {
      "todo": 3,
      "doing": 1,
      "review": 0,
      "done": 2,
      "total": 6
    }
  }
]
```

Progress stats are computed by joining `items` on `epic_id` and grouping by `column_name`.

### Item create/edit

Existing `POST /api/items` and `PUT /api/items/{id}` accept optional `epic_id` field. Validated against existing epic IDs.

### WebSocket events

- `epic_created`, `epic_updated`, `epic_deleted` — broadcast on epic mutations
- Existing `item_updated` already covers item epic assignment changes

### Database service

Add to `DatabaseService`:
- `get_epics()` — all epics ordered by position
- `get_epic_progress()` — item counts per column per epic
- `create_epic(title, color)` — insert with auto-position
- `update_epic(id, fields)` — partial update
- `delete_epic(id)` — delete epic, nullify `epic_id` on related items

### Notification service

Add `broadcast_epic_created`, `broadcast_epic_updated`, `broadcast_epic_deleted` to `NotificationService`.

## Frontend

### Epic Panel (above board)

- Collapsible horizontal panel between stats bar and board columns
- Toggle button in header area (e.g., "Epics" with chevron)
- Collapsed by default
- Each epic rendered as a compact card:
  - Colored dot + title
  - Progress bar (done / total items)
  - Item count label (e.g., "2/6")
- Click an epic card to filter the board
- When filtered: "clear filter" button appears, board shows only items with that `epic_id`
- Panel state (collapsed/expanded) persisted in localStorage

### Todo Column Grouping

- When no epic filter is active, Todo items grouped by epic
- Each group: collapsible section with epic color dot + title header (reuse Done column day-group pattern)
- "No Epic" group at the bottom for ungrouped items
- When epic filter is active, no grouping needed (all shown items belong to one epic)

### Card Badge

- Small colored dot + epic name shown on cards in all columns (Doing, Review, Done)
- Subtle — does not affect card layout significantly
- Omitted when epic filter is active (redundant)

### Item Dialog — Epic Assignment

- Epic dropdown in new/edit item form (below title, above description)
- Shows colored dot + epic name for each option
- First option: "No Epic" (clears assignment)
- Last option: "+ Create new epic" — expands inline fields:
  - Title text input
  - Color picker: row of 8 preset color swatches
  - "Create" button — creates epic via API, selects it in dropdown
- Dropdown also used in "Save & Start" flow

### CSS

- Epic panel styles added to `board.css`
- Epic color variables/utilities added to `style.css`
- Dark theme overrides in `theme.css`

## Agent Integration

### `view_board` MCP tool

Updated response includes `epic` field per item:

```json
{
  "title": "Fix login bug",
  "epic": { "title": "Auth Rewrite", "color": "blue" }
}
```

### `create_todo` MCP tool

Accepts optional `epic_id` parameter. Agents can assign new todos to epics.

## Stats

`GET /api/stats` updated to include per-epic breakdowns if epics exist. Stats cache invalidated on epic mutations.

## Deletion Behavior

- Deleting an epic nullifies `epic_id` on all related items (items are not deleted)
- Confirmation dialog before deletion showing affected item count
- Items move to "No Epic" group in Todo

## What's NOT included

- Epic descriptions or due dates (YAGNI)
- Nested epics / hierarchy
- Epic-level agent orchestration (start all items in an epic)
- Drag-drop reordering of epics in the panel (position set via API only)
