# CLAUDE.md

Standalone scrum board that orchestrates Claude agents working on a **separate target project**. Server code lives here; data directory (`agents-lab/`) is created in the target project.

## Running

```bash
./run.sh /path/to/target-project   # Creates venv, installs deps, starts server (Python 3.12+)
./run-tests.sh                     # All tests (177)
./run-tests.sh tests/smoke/        # Smoke tests only
./run-tests.sh -k "test_cancel"    # Filter by name
```

Server binds to `127.0.0.1:8000` (auto-increments if busy, up to 8019). E2E tests: `./run-e2e-tests.sh`.

## Architecture

**Backend**: FastAPI + aiosqlite. `AgentOrchestrator` is a thin facade delegating to 5 services:
- `WorkflowService` — agent lifecycle, state transitions, merge conflict auto-resolution, dependency auto-start
- `DatabaseService` — all DB operations
- `NotificationService` — WebSocket broadcasting
- `GitService` — worktree management, merge operations
- `SessionService` — Claude SDK session lifecycle, commit messages

**Frontend**: Vanilla JS, no build step. Jinja2 server-renders initial board; JS handles updates via WebSocket + fetch. `dialogs.js` coordinates 12 specialized dialog modules.

**Database**: SQLite with 12 versioned migrations in `src/migrations/versions/`. Auto-migrates on startup. CLI: `python -m src.manage [status|migrate|rollback]`.

### Key flows

- **Agent start**: non-blocking via `asyncio.create_task()`. Each item gets its own git worktree (`agents-lab/worktrees/agent-{item_id}`).
- **Clarification**: `ask_user` MCP tool moves item to "Clarify", `await`s `asyncio.Event`, HTTP endpoint sets the event.
- **Merge**: commits uncommitted worktree changes first, then merges. On conflict, captures diff, resets worktree to latest base, restarts agent with conflict prompt.
- **Pause/resume**: captures `session_id`, kills process, later resumes via `ClaudeAgentOptions(resume=session_id, continue_conversation=True)`.
- **Stale worktree detection**: on startup + every 5min, scans worktrees against DB state, emits cleanup notifications.

### Built-in MCP tools

`ask_user`, `create_todo` (with `requires` for dependencies), `set_commit_message`, `request_command_access`, `view_board`, `request_tool_access`, `create_shortcut`.

## Important patterns

- All state changes broadcast via `NotificationService` for real-time UI.
- `TemplateResponse` requires `request` as first kwarg: `TemplateResponse(request=request, name="...", context={...})`.
- Never use browser `confirm()` or `prompt()` in dialogs — use `Dialogs.confirm()` (returns Promise).
- Tooltips use `position: fixed`, appended to nearest open `<dialog>` or `document.body`. Use `data-tip` / `data-tip-html`.
- Card action buttons use `event.stopPropagation()` on individual buttons, not on the wrapper div.
- Avoid duplicate `from pathlib import Path` inside functions — it's imported at file top and causes `UnboundLocalError`.
- Annotations export two PNGs: `_original.png` (clean) and `_annotations.png` (overlay). The `annotation_summary` column stores a text count.
- Agents run with `permission_mode="acceptEdits"` by default. YOLO mode uses `bypassPermissions`.
- Allowed command prefixes are checked via `PreToolUse` hook (`command_filter.py`). Denied commands prompt `request_command_access`.
- Optional built-in tools (WebSearch, WebFetch) filtered via `PreToolUse` hook (`tool_filter.py`). Denied tools prompt `request_tool_access`.
- External MCP servers get wildcard tool permissions (`mcp__{server_name}__*`).
- Attachment deletion uses `/api/attachments/{attachment_id}` (not nested under items).
- JavaScript-rendered cards and the server-rendered Jinja2 `card.html` partial must stay in sync.
- Notifications support optional `action` dict (`{label, url, method}`) for action buttons (e.g., stale worktree cleanup).

## Development workflows

### Adding features

1. **Backend**: models.py -> migration in `src/migrations/versions/` -> service logic -> routes.py endpoint
2. **Frontend**: templates + dialog module + WebSocket event handling in `app.js` + broadcast from `NotificationService`
3. **DB migration**: copy `000_template.py.example`, implement `up()`/`down()`, test with `python -m src.manage migrate`

### Debugging

- **Agent issues**: check work log. Extended thinking: `budget_tokens: 10000` (adjustable).
- **WebSocket**: browser dev tools -> Network -> WS tab.
- **Git worktrees**: `git worktree list` to find orphans. Dashboard detects stale worktrees automatically.
- **Database**: `sqlite3 agents-lab/dashboard.db ".schema"` or `"SELECT * FROM items;"`
- **Migrations**: `python -m src.manage status`
