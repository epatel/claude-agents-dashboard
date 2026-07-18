# Architecture

> **Load when**: first orienting on this codebase, or you need to know which file/service owns a concept.
> **Skip when**: you already know the layout.

Tour of the major subsystems. For named flows with line-numbered entry points see [`PROJECT_MAP.md`](PROJECT_MAP.md).

## Backend services

FastAPI + aiosqlite. `AgentOrchestrator` (`src/agent/orchestrator.py`) is a thin facade delegating to 7 services in `src/services/`:

- `WorkflowService` (~1800 LOC) — agent lifecycle, state transitions (driven by `ItemState` FSM in `src/domain/item_state.py`), merge conflict auto-resolution, dependency auto-start, WIP limit queueing, single/multi-repo session kwargs (`_item_session_kwargs`), pause/resume with session capture, post-merge graph refresh
- `DatabaseService` (~570 LOC) — all DB operations (parameterized; column whitelists live in the repositories)
- `NotificationService` — WebSocket broadcasting + tool formatting; the single fan-out point on every state change (incl. graphify `graph_build_progress` / `graph_ready` events)
- `GitService` — worktree management, merge operations, repo path resolution
- `SessionService` — Claude SDK session lifecycle, commit messages, plugin parsing, Ollama config
- `GraphService` — graphify knowledge graph: build/refresh/query/status, version detection, cost tracking; shells out to the `graphify` venv binary and owns `graphify-out/`
- `SkillsService` — dashboard-managed library of Agent Skills: install/list/remove, browse Anthropic's public repo, discover skills in any GitHub repo/path; installs into a gitignored `skill-library/<name>/` (each wrapped as a one-skill plugin). Per-project enable lives in `agent_config.enabled_skills`; `SessionService._parse_plugins` resolves enabled names to plugin paths and merges them into the SDK `plugins=` list (so skills load regardless of git/worktree/`setting_sources`)

## Web layer (`src/web/`)

- `app.py` — FastAPI app + lifespan (runs DB migrations, the startup state-encoding audit `_audit_item_state_encodings`, and the periodic stale-worktree scanner)
- `routes.py` — board/item/epic/clarification/shortcut/notifications/stats/graphify HTTP endpoints (~1650 LOC)
- `file_routes.py` — attachments + file browser
- `websocket.py` — WS connection manager

## Agent runtime (`src/agent/`)

Claude SDK integration plus built-in MCP tool servers and PreToolUse hooks. One file per concern.

**MCP tool servers**:
- `clarification.py` — `ask_user`
- `todo.py` — `create_todo` / `create_epic` / `delete_todo`
- `board_view.py` — `view_board`
- `who_am_i.py` — `who_am_i` (returns the agent's OWN item — id, title, column, deps — so it can self-reference in `requires` without guessing from `view_board`)
- `commit_message.py` — `set_commit_message`
- `command_access.py` — `request_command_access`
- `tool_access.py` — `request_tool_access`
- `shortcut.py` — `create_shortcut`
- `graph_query.py` — `graph_query` (read-only knowledge-graph query; only wired in when `graphify_enabled`)

**PreToolUse hooks**:
- `command_filter.py` — denies shell commands not in the allowlist
- `tool_filter.py` — denies built-in tools (WebSearch, WebFetch) not allowed
- `path_guard.py` — denies Read/Edit/Write outside the worktree

**Plus**:
- `base.py` — `AbstractAgentSession` contract (start/cancel + `current_session_id`/`on_error`) and the `AgentResult` dataclass; a future non-Claude runtime implements this
- `profiles.py` — provider profiles: `is_ollama_model` / `resolve_ollama_env` routing plus the `AgentProfile` that carries the divergent SDK options and feature gates (Ollama = a profile of the Claude runtime, not a separate runtime)
- `session.py` — `ClaudeAgentSession` (Claude Agent SDK wrapper): system prompt + tool wiring
- `orchestrator.py` — the public facade

External MCP servers get wildcard tool permissions (`mcp__{server_name}__*`).

## Domain & repositories

- `src/domain/item_state.py` — explicit `ItemState` finite state machine over the 13 reachable states (encoded in DB as the `(column_name, status)` pair). All workflow transitions go through `transition(state, event)`; storage encoding stays unchanged via `from_columns` / `to_columns`. **Raw `column_name` / `status` writes outside the SM are a regression.**
- `src/repositories/item_repository.py` — facade over `DatabaseService` for items; owns `_WRITABLE_ITEM_COLUMNS` and exposes intent-named operations (`get_or_raise`, `transition()`, `update_fields()`, `move_item`).
- `src/repositories/epic_repository.py` — equivalent facade for epics; the `_WRITABLE_EPIC_COLUMNS` whitelist lives here.
- `src/models.py::AgentConfig` — JSON-string fields (`tools`, `mcp_servers`, `plugins`, `allowed_commands`, `allowed_builtin_tools`) are real Python types; validators tolerate raw JSON strings on input so DB rows still load.

## Frontend

Vanilla JS in `src/static/js/`, **no build step**.

- Jinja2 server-renders the initial board (`templates/base.html`, `templates/board.html`, `templates/partials/card.html`)
- JS handles updates via WebSocket + fetch
- `dialogs.js` coordinates the specialized dialog modules (clarification, config, detail, item, notification, request-changes, review, search, file-browser, attachments, shortcuts, annotate)
- `dialog-core.js` + `dialog-utils.js` are the shared infrastructure
- **Sync requirement**: JavaScript-rendered cards (in `board.js`) and the server-rendered Jinja2 `partials/card.html` partial must stay in sync.

## Adding a feature: where things go

1. **Backend**: `models.py` → migration in `src/migrations/versions/` → service logic (`services/workflow|database|git|session`) and/or repository method → endpoint in `web/routes.py` (or `web/file_routes.py` for attachments). Workflow state changes must go through `ItemState.transition()`.
2. **Frontend**: templates + dialog module in `src/static/js/` + WebSocket event handling in `app.js` + broadcast from `NotificationService`.
3. **MCP tool / hook**: drop a new file in `src/agent/`, register it from `session.py`'s tool/server wiring, and (if it's a hook that can deny) make sure the agent has a way to request access — see `command_access` / `tool_access` for the pattern.

---

**See also**: [CONVENTIONS](CONVENTIONS.md) (how to write the code once you know where), [PROJECT_MAP](PROJECT_MAP.md) (line-numbered entry points for each named flow).
