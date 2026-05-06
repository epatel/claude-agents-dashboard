# Domain & Repositories

- `src/domain/item_state.py` — explicit `ItemState` finite state machine over the 13 reachable states (encoded in DB as the `(column_name, status)` pair). All workflow transitions go through `transition(state, event)`; storage encoding stays unchanged via `from_columns` / `to_columns`.
- `src/repositories/item_repository.py` — facade over `DatabaseService` for items; owns `_WRITABLE_ITEM_COLUMNS` and exposes intent-named operations (`get_or_raise`, `transition()`, `update_fields()`, `move_item`).
- `src/repositories/epic_repository.py` — equivalent facade for epics; the `_WRITABLE_EPIC_COLUMNS` whitelist lives here.
- `src/models.py::AgentConfig` — JSON-string fields (`tools`, `mcp_servers`, `plugins`, `allowed_commands`, `allowed_builtin_tools`) were promoted to real Python types (Phase 3); validators tolerate raw JSON strings on input so DB rows still load.

Workflow state changes must go through `ItemState.transition()` in `src/domain/item_state.py`; raw `column_name` / `status` writes outside the SM are a regression.
