# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the project

```bash
# From a target git repo (the project agents will work on):
path/to/claude-agents-dashboard/run.sh

# Or with explicit path:
./run.sh /path/to/target-project
```

`run.sh` creates the venv if needed, installs deps, and launches `python -m src.main <target>`. Server binds to 127.0.0.1:8000 (auto-increments if busy).

**No test suite exists yet.** To verify changes, start the server against a test git repo and exercise the UI.

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

- **Session resumption**: `ResultMessage.session_id` is stored in the DB. When requesting changes, the agent resumes its previous session via `ClaudeAgentOptions(resume=session_id, continue_conversation=True)` so it retains full conversation context.

- **Diff includes uncommitted changes**: `get_diff()` and `get_changed_files()` accept a `worktree_path` parameter. When provided, they combine committed branch diff + uncommitted changes + untracked files, since agents don't always commit their work.

- **Merge commits worktree first**: `merge_branch()` calls `commit_worktree_changes()` before merging, handling agents that leave uncommitted work.

### Frontend

Vanilla JS with no build step. Server-renders the initial board via Jinja2; JavaScript handles all subsequent updates via WebSocket events and fetch API. `marked.js` (CDN) renders markdown in descriptions and work logs.

Key JS modules: `app.js` (WebSocket + init), `board.js` (drag-drop + card rendering), `dialogs.js` (all modals + custom confirm), `api.js` (HTTP helpers), `diff.js` (diff viewer), `annotate.js` (annotation canvas).

### Database

SQLite via aiosqlite. Schema in `database.py`. Tables: `items` (board cards + git metadata), `work_log` (agent activity stream), `review_comments`, `clarifications`, `attachments` (annotated images), `agent_config` (single-row settings).

## Important patterns

- All state changes broadcast via `ws_manager.broadcast(event_type, data)` for real-time UI updates.
- The `_update_item` helper in orchestrator updates DB + broadcasts in one call.
- `Starlette TemplateResponse` requires `request` as first kwarg: `TemplateResponse(request=request, name="...", context={...})`.
- Agent's `cwd` is set to the worktree path, and the system prompt explicitly tells the agent its working directory. `add_dirs` is also set to allow file operations there.
- Extended thinking is enabled (`thinking={"type": "enabled", "budget_tokens": 10000}`) for richer agent reasoning.
- Never use browser `confirm()` or `prompt()` in dialogs — they block and conflict with `<dialog>` modals. Use `Dialogs.confirm()` which returns a Promise.
- Tooltips use JS positioning (`position: fixed`, appended to `document.body`) to escape dialog `overflow: hidden`.
- Avoid duplicate `from pathlib import Path` inside functions — it's imported at file top and local imports cause `UnboundLocalError`.
- Attachments are stored as PNG files in `agents-lab/assets/` and referenced in the `attachments` table. Cleaned up on item delete.
- The annotation canvas (`annotate.js`) is a self-contained component: `Annotate.init(canvasEl)` to start, `Annotate.toDataURL()` to export. Supports image drop, scale (wheel + corner handles), and annotation tools.
- Card action buttons use `event.stopPropagation()` on individual buttons, not on the wrapper div, to avoid click blind spots.
