# CLAUDE.md

Standalone scrum board that orchestrates Claude agents working on a **separate target project** (or a workspace of sibling git repos in multi-repo mode). Server code lives here; data directory (`agents-lab/`) is created in the target project / workspace root.

## Running

```bash
./run.sh /path/to/target-project    # Single-repo mode — creates venv, installs deps, starts server (Python 3.12+)
./run.sh /path/to/workspace-folder  # Multi-repo mode — workspace must contain ≥1 sibling git repos
./run.sh /path/to/project --experimental  # Enable experimental features (Ollama provider, Sonnet 4.6 + Advisor)
./run-tests.sh                      # All tests (873)
./run-tests.sh tests/smoke/         # Smoke tests only
./run-tests.sh -k "test_cancel"     # Filter by name
```

Server binds to `127.0.0.1:8000` (auto-increments if busy, up to 8019). E2E tests: `./run-e2e-tests.sh`.

## Architecture

**Backend**: FastAPI + aiosqlite. `AgentOrchestrator` is a thin facade delegating to 5 services:
- `WorkflowService` — agent lifecycle, state transitions, merge conflict auto-resolution, dependency auto-start, WIP limit queueing, multi-repo session kwargs
- `DatabaseService` — all DB operations (parameterized, with column whitelists)
- `NotificationService` — WebSocket broadcasting + tool formatting
- `GitService` — worktree management, merge operations, repo path resolution
- `SessionService` — Claude SDK session lifecycle, commit messages, plugin parsing, Ollama config

**Frontend**: Vanilla JS, no build step. Jinja2 server-renders initial board (`base.html`, `board.html`, `partials/card.html`); JS handles updates via WebSocket + fetch. `dialogs.js` coordinates 12 specialized dialog modules.

**Database**: SQLite with 20 versioned migrations (001–020) in `src/migrations/versions/`. Auto-migrates on startup. CLI: `python -m src.manage [status|migrate|rollback]`.

**Models**: Default is **Claude Opus 4.7**. Other selectable models: Claude Sonnet 4.6, Claude Haiku 4.5, and Claude Sonnet 4.6 + Advisor (experimental). Optional Ollama provider gated behind `--experimental`.

### Key flows

- **Agent start**: non-blocking via `asyncio.create_task()`. Each item gets its own git worktree (`agents-lab/worktrees/agent-{item_id}`). In multi-repo mode the worktree is rooted in the item's chosen sibling repo and `add_dirs` includes the other sibling repos read-only.
- **Clarification**: `ask_user` MCP tool moves item to "Clarify", `await`s `asyncio.Event`, HTTP endpoint sets the event.
- **Merge**: commits uncommitted worktree changes first, then merges. On conflict, captures diff, resets worktree to latest base, restarts agent with conflict prompt.
- **Pause/resume**: captures `session_id`, kills process, later resumes via `ClaudeAgentOptions(resume=session_id, continue_conversation=True)`.
- **Stale worktree detection**: on startup + every 5min, scans worktrees against DB state, emits cleanup notifications.
- **WIP limit**: configurable cap on concurrent running agents; items started beyond the limit are placed in 'doing' with `status='queued'` and auto-started in position order when a slot opens.
- **Multi-repo**: when `target_project` is a parent folder containing ≥1 sibling git repos, items carry a required `repo` field; worktrees are created inside the chosen subrepo.

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
- Path guard via `PreToolUse` hook (`path_guard.py`) prevents agents from editing files outside their worktree.
- External MCP servers get wildcard tool permissions (`mcp__{server_name}__*`).
- Attachment deletion uses `/api/attachments/{attachment_id}` (not nested under items).
- JavaScript-rendered cards and the server-rendered Jinja2 `card.html` partial must stay in sync.
- Notifications support optional `action` dict (`{label, url, method}`) for action buttons (e.g., stale worktree cleanup).

## Development workflows

### Adding features

1. **Backend**: models.py -> migration in `src/migrations/versions/` -> service logic (workflow/database/git/session) -> routes.py endpoint
2. **Frontend**: templates + dialog module + WebSocket event handling in `app.js` + broadcast from `NotificationService`
3. **DB migration**: copy `000_template.py.example`, implement `up()`/`down()`, test with `python -m src.manage migrate`. Whitelist any new `items`/`epics` columns in `database_service.py` (`ALLOWED_ITEM_COLUMNS` / `ALLOWED_EPIC_COLUMNS`).
4. **Card rendering**: keep JS card builder in `board.js` and the Jinja2 `partials/card.html` partial in sync.

### Debugging

- **Agent issues**: check work log. Extended thinking: `budget_tokens: 10000` (adjustable).
- **WebSocket**: browser dev tools -> Network -> WS tab.
- **Git worktrees**: `git worktree list` to find orphans. Dashboard detects stale worktrees automatically.
- **Database**: `sqlite3 agents-lab/dashboard.db ".schema"` or `"SELECT * FROM items;"`
- **Migrations**: `python -m src.manage status`
