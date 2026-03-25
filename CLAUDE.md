# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the project

```bash
# From a target git repo (the project agents will work on):
path/to/claude-agents-dashboard/run.sh

# Or with explicit path:
./run.sh /path/to/target-project
```

`run.sh` creates the venv if needed, installs deps from `requirements.txt`, and launches `python -m src.main <target>`. Server binds to 127.0.0.1:8000 (auto-increments if busy). Requires Python 3.12+.

**No automated test suite exists yet.** To verify changes, start the server against a test git repo and exercise the UI manually, including testing agent workflows, clarification flows, and todo creation features.

## Architecture

This is a standalone scrum board tool that orchestrates Claude agents working on a **separate target project**. The server code lives here; the data directory (`agents-lab/`) is created in the target project.

### Request flow

```
Browser ←WebSocket→ ConnectionManager (websocket.py)
Browser ←HTTP→ FastAPI routes (routes.py)
                ↓
         AgentOrchestrator (orchestrator.py)
           ↓              ↓
    AgentSession      Git operations
    (session.py)      (git/operations.py, git/worktree.py)
         ↓
    ClaudeSDKClient (claude-agent-sdk)
```

### Key design decisions

- **Agent start is non-blocking**: `start_agent` launches the agent via `asyncio.create_task(_run_agent(...))` so the HTTP response returns immediately. The agent streams progress via WebSocket.

- **One worktree per item**: Each agent task gets a git worktree (`agents-lab/worktrees/agent-{item_id}`) branched off main. This allows multiple agents to run simultaneously without conflicts.

- **Clarification uses asyncio.Event**: When an agent calls the `ask_user` MCP tool, the orchestrator's `_on_clarify` callback moves the item to "Clarify", broadcasts to the frontend, and `await`s an `asyncio.Event`. The HTTP endpoint `submit_clarification` sets the event, unblocking the agent.

- **Todo creation via MCP**: Agents can create new todo items via the `create_todo` MCP tool. This flows through `_on_create_todo` callback, creates new items in the database with proper positioning, and broadcasts real-time updates to the frontend.

- **Per-item model selection**: Items can have an individual `model` field (migration 003). `start_agent()` uses `item.get("model") or config.get("model")`, falling back to the global agent config default (`claude-sonnet-4-20250514`).

- **Session resumption**: `ResultMessage.session_id` is stored in the DB. When requesting changes, the agent resumes its previous session via `ClaudeAgentOptions(resume=session_id, continue_conversation=True)` so it retains full conversation context.

- **Diff includes uncommitted changes**: `get_diff()` and `get_changed_files()` accept a `worktree_path` parameter. When provided, they combine committed branch diff + uncommitted changes + untracked files, since agents don't always commit their work.

- **Merge commits worktree first**: `merge_branch()` calls `commit_worktree_changes()` before merging, handling agents that leave uncommitted work. Uses agent-provided commit messages when available (via `set_commit_message` MCP tool).

- **Merge conflict handling**: If a merge conflict occurs, the item moves to `resolving_conflicts` status and the merge is aborted, keeping the worktree intact.

- **Cost tracking**: Agent completion logs USD cost via `result.cost_usd` from the Claude SDK, displayed in the work log.

- **Retry reuses worktree**: `retry_agent()` cancels any existing session, reuses the existing worktree if present, and starts a fresh agent run. It does not resume the previous session.

- **Delete cleans up everything**: Deleting an item stops any running agent, removes the git worktree and branch, deletes attachment files from disk, and cascades deletes to `work_log`, `review_comments`, `clarifications`, and `attachments` tables.

- **External MCP tool allowance**: External MCP servers loaded from `mcp-config.json` get wildcard tool permissions (`mcp__{server_name}__*`). Built-in servers (`clarification`, `todo`, `commit_message`) get explicit individual tool permissions instead.

- **Work log tool formatting**: `_format_tool_use()` renders human-readable summaries for common tools (Write, Edit, Read, Bash, Glob, Grep, ask_user, create_todo, set_commit_message). Unknown tools show a truncated input summary.

- **Last agent message tracking**: `_last_agent_messages` dict tracks the latest text message per item for quick access without querying the work log.

### Frontend

Vanilla JS with no build step. Server-renders the initial board via Jinja2; JavaScript handles all subsequent updates via WebSocket events and fetch API. `marked.js` (CDN) renders markdown in descriptions and work logs.

Key JS modules: `app.js` (WebSocket + init), `board.js` (drag-drop + card rendering), `dialogs.js` (all modals + custom confirm), `api.js` (HTTP helpers), `diff.js` (diff viewer), `annotate.js` (annotation canvas), `theme.js` (light/dark mode toggle).

### Database

SQLite via aiosqlite with a versioned migration system. Migration files are in `src/migrations/versions/` (currently 4 migrations: 001 initial schema, 002 MCP support, 003 per-item model, 004 commit messages). Tables: `items` (board cards + git metadata + model + commit_message), `work_log` (agent activity stream with JSON metadata), `review_comments`, `clarifications`, `attachments` (annotated images), `agent_config` (single-row settings with MCP config), `schema_migrations` (migration tracking). Agents can create new todo items directly via MCP tools, automatically positioned in the todo column.

Note: Attachment deletion uses `/api/attachments/{attachment_id}` (not nested under items) since attachments have their own integer IDs.

#### Migration System

- **Migration runner**: `src/migrations/runner.py` manages applying/rolling back migrations
- **Migration files**: `src/migrations/versions/XXX_description.py` contain versioned schema changes
- **Schema tracking**: `schema_migrations` table tracks which migrations have been applied
- **CLI management**: `python -m src.manage` for migration commands
- **Auto-migration**: Database automatically runs pending migrations on startup

## Important patterns

- All state changes broadcast via `ws_manager.broadcast(event_type, data)` for real-time UI updates.
- The `_update_item` helper in orchestrator updates DB + broadcasts in one call.
- `Starlette TemplateResponse` requires `request` as first kwarg: `TemplateResponse(request=request, name="...", context={...})`.
- Agent's `cwd` is set to the worktree path, and the system prompt explicitly tells the agent its working directory. `add_dirs` is also set to allow file operations there. Agent sessions use `permission_mode="acceptEdits"` for targeted autonomy (more restricted than `bypassPermissions`).
- Extended thinking is enabled (`thinking={"type": "enabled", "budget_tokens": 10000}`) for richer agent reasoning.
- Never use browser `confirm()` or `prompt()` in dialogs — they block and conflict with `<dialog>` modals. Use `Dialogs.confirm()` which returns a Promise.
- Tooltips use JS positioning (`position: fixed`, appended to the nearest open `<dialog>` or `document.body`) so they appear above modal dialogs. Use `data-tip` for plain text, `data-tip-html` for rich formatted tooltips.
- Avoid duplicate `from pathlib import Path` inside functions — it's imported at file top and local imports cause `UnboundLocalError`.
- Attachments are stored as PNG files in `agents-lab/assets/` and referenced in the `attachments` table. Cleaned up on item delete.
- The annotation canvas (`annotate.js`) is a self-contained component: `Annotate.init(canvasEl)` to start, `Annotate.toDataURL()` to export. Supports image drop, scale (wheel + corner handles), and annotation tools.
- Card action buttons use `event.stopPropagation()` on individual buttons, not on the wrapper div, to avoid click blind spots.
- MCP tool callbacks follow async patterns: clarification uses `asyncio.Event` for user response, todo creation immediately returns success and broadcasts updates, commit message stores in-memory (`_commit_messages` dict) and persists to DB on agent completion.
- Agent-created items are indistinguishable from manually created ones in the database and UI — they follow the same lifecycle and support all features.
- Port auto-discovery scans 8000–8019 (`MAX_PORT_TRIES = 20` in `config.py`).

## Development workflows

### Adding new features

1. **Backend changes**:
   - Update models in `models.py`
   - Create database migration in `src/migrations/versions/` for schema changes
   - Implement business logic in `orchestrator.py`
   - Add HTTP endpoints in `routes.py`

2. **Database changes**:
   - Copy `src/migrations/versions/000_template.py.example` to `XXX_description.py`
   - Update version number sequentially (e.g., `003`, `004`, etc.)
   - Implement `up()` method for schema changes and `down()` method for rollback
   - Test migration with `python -m src.manage migrate` and rollback with `python -m src.manage rollback`

3. **Frontend changes**: Add HTML in templates (`web/static/`), update JavaScript modules, handle WebSocket events in `app.js`, broadcast state changes from backend.

4. **Agent capabilities**: Extend the system prompt in `AgentOrchestrator.create_agent()`, add MCP tools via the agent config UI, or modify `ask_user` clarification flows or `create_todo` workflows.

### Testing changes

Since no automated test suite exists, manually verify changes by:
- Starting the server against a test git repository
- Creating board items and testing the full agent workflow
- Testing edge cases: git conflicts, agent failures, clarification flows
- Testing agent MCP tools: clarification prompts, todo creation
- Checking WebSocket updates in browser dev tools for real-time features
- Verifying git worktree cleanup after item completion
- Testing todo creation: ensure agents can create items that appear properly positioned

### Debugging

**Agent issues**: Check the work log for detailed agent output. Enable more verbose logging by setting `thinking={"type": "enabled", "budget_tokens": 20000}` in agent options.

**WebSocket problems**: Open browser dev tools → Network tab → WS → check for connection errors. The server logs WebSocket events to console.

**Git worktree issues**: Check `agents-lab/worktrees/` for orphaned directories. Clean up manually if needed:
```bash
git worktree list
git worktree remove agents-lab/worktrees/agent-XXXXX
```

**Database problems**: The SQLite file is at `agents-lab/dashboard.db`. Use `sqlite3` CLI or DB Browser to inspect:
```bash
sqlite3 agents-lab/dashboard.db ".schema"
sqlite3 agents-lab/dashboard.db "SELECT * FROM items;"
```

**Migration issues**: Use the migration CLI to debug schema problems:
```bash
python -m src.manage status  # Check current state
python -m src.manage migrate  # Apply pending migrations
python -m src.manage rollback 001  # Rollback to version 001
```

**Performance**: The app is designed for localhost use. For large repositories, git operations may be slow. Consider shallow clones for worktrees if needed.

### Adding new MCP tools

1. Create the tool server following MCP spec
2. Update agent config via the UI to include your MCP server
3. Test via the agent clarification flow or direct tool use
4. Document new tools in the agent system prompt if they require specific usage patterns

### Built-in MCP tools

The system includes several built-in MCP tools for agents:

- **`ask_user`** (clarification): Allows agents to ask users questions and wait for responses. Moves items to "Clarify" column and resumes when answered.
- **`create_todo`** (todo creation): Enables agents to create new todo items with title and optional description. Items are automatically positioned in the todo column and broadcast to all connected clients.
- **`set_commit_message`** (commit message): Allows agents to set a custom commit message for their work. Stored in the database and used during merge instead of the generic "Agent work on agent/xxx" message.
