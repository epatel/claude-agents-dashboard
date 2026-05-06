# Web Layer

**Web layer** (`src/web/`): split into:

- `app.py` — FastAPI app + lifespan
- `routes.py` — board/item/epic/clarification HTTP endpoints, ~1500 LOC
- `file_routes.py` — attachments + file browser
- `websocket.py` — WS connection manager

`app.py::lifespan` runs DB migrations, the startup state-encoding audit (`_audit_item_state_encodings`), and the periodic stale-worktree scanner.
