# Development Workflows

## Adding features

1. **Backend**: `models.py` → migration in `src/migrations/versions/` → service logic (`services/workflow|database|git|session`) and/or repository method (`repositories/item_repository.py`, `repositories/epic_repository.py`) → endpoint in `web/routes.py` (or `web/file_routes.py` for attachments). Workflow state changes must go through `ItemState.transition()` in `src/domain/item_state.py`; raw `column_name` / `status` writes outside the SM are a regression.
2. **Frontend**: templates + dialog module in `src/static/js/` + WebSocket event handling in `app.js` + broadcast from `NotificationService`.
3. **DB migration**: copy `000_template.py.example`, implement `up()`/`down()`, test with `python -m src.manage migrate`. Whitelist any new `items` columns in `repositories/item_repository.py` (`_WRITABLE_ITEM_COLUMNS`) and any new `epics` columns in `repositories/epic_repository.py` (`_WRITABLE_EPIC_COLUMNS`). Add a unit test under `tests/unit/migrations/`.
4. **Card rendering**: keep JS card builder in `board.js` and the Jinja2 `partials/card.html` partial in sync.
5. **MCP tool / hook**: drop a new file in `src/agent/`, register it from `session.py`'s tool/server wiring, and (if it's a hook that can deny) make sure the agent has a way to request access — see `command_access` / `tool_access` for the pattern.

## Debugging

- **Agent issues**: check work log. Extended thinking: `budget_tokens: 10000` (adjustable).
- **WebSocket**: browser dev tools → Network → WS tab.
- **Git worktrees**: `git worktree list` to find orphans. Dashboard detects stale worktrees automatically.
- **Database**: `sqlite3 agents-lab/dashboard.db ".schema"` or `"SELECT * FROM items;"`
- **Migrations**: `python -m src.manage status`
