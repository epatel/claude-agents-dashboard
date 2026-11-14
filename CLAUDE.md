# CLAUDE.md

Standalone scrum board that orchestrates Claude agents working on a **separate target project** (or a workspace of sibling git repos in multi-repo mode). Server code lives here; data directory (`agents-lab/`) is created in the target project / workspace root.

## Known stack — use what you already know

Standard and used the standard way: read the code and apply the usual idioms. The cards cover what is project-specific.

- **FastAPI + uvicorn**: `create_app` / `lifespan` in `src/web/app.py`; shared objects on `app.state` (`db`, `orchestrator`, `ws_manager`). Each route group is an `APIRouter` in `src/web/*_routes.py`, included into `routes.router`.
- **Pydantic v2** request and config models in `src/models.py`.
- **aiosqlite / SQLite**: `Database` in `src/database.py`; schema changes only through numbered migrations in `src/migrations/versions/`.
- **Jinja2 + plain browser JS**: no bundler, no ES modules. Each `src/static/js/*.js` defines one global object (`const Api = {…}`), loaded by `<script>` tags in `src/templates/base.html` / `board.html` in dependency order; CDN libraries (marked, DOMPurify, mermaid, Prism) are globals too.
- **WebSocket** `/ws`, broadcast through `ConnectionManager` (`src/web/websocket.py`).
- **claude-agent-sdk** (`ClaudeSDKClient`, `ClaudeAgentOptions`) runs agents; the session layer around it is custom (see cards).
- **pytest + pytest-asyncio** (`asyncio_mode = auto`), route tests via httpx `AsyncClient` + `ASGITransport`; **Playwright (Node)** for `tests/e2e/*.mjs`.
- **SwiftUI** macOS wrapper in `wrappers/macos` (SwiftPM + Xcode project).

## Quick start

```bash
./run.sh /path/to/target-project    # Single-repo mode
./run.sh /path/to/workspace-folder  # Multi-repo mode
./run.sh /path/to/project --experimental  # Experimental features (Ollama + Tiiny + Kimi providers)
./run.sh /path/to/project --ui-map        # PROJECT_MAP overlays (Cmd+Shift+M)
./run-tests.sh                      # All tests (unit/integration/smoke — count in CARDS/TESTING.md)
./run-tests.sh tests/unit/test_x.py -k name  # One file / dir / test (any path narrows the run)
./run-e2e-tests.sh                  # E2E tests (Node Playwright, spawns agents)
```

Server binds to `127.0.0.1:8000` (auto-increments up to 8019).

## Shared plan

@project-plan.md

Always read the shared plan above before starting — it holds the shared goal and current state across agents. When spawning subagents or worktree agents, tell them to read it first and to update its **Current state** and **Decisions** sections before finishing.

## Docs

Before doing real work, scan **[`AGENT_FILES/CARDS/README.md`](AGENT_FILES/CARDS/README.md)** — the routing manifest — and load only the cards whose **Load when** matches the task. Don't bulk-load.

Project skills live in `.claude/skills/` (committed): `review-agentic-setup` and `files-skill` for maintaining this setup, `ste-writing` for doc prose, `double-check` before committing or shipping a change.

`AGENT_FILES/` root holds historical snapshots (`ASSESSMENT_CODE.md`, dated `PLAN_*`/`EVAL_*` records) — don't edit those to match current state. Two exceptions (see Decisions): `AUDIT.md` gets a new rev when agent-facing surface is added, and `SDK_BUMP_*.md` gets a rev note per SDK bump. Living docs are under `CARDS/`, plus [`docs/item-states.md`](docs/item-states.md) (the `ItemState` FSM and its diagram, kept in sync with `src/domain/item_state.py`).

## Code health

- Before committing, run `aihealth delta` and fix new or worsened smells it reports
  in code you touched (exit code 1 = health degraded).
- `aihealth scan .` gives an overview of the codebase.
- A full `./run-tests.sh` (no test path) also fails if the score drops below the floors in
  `HEALTH_FLOORS` in `run-tests.sh` (project 9.5, `src/` 9.6); `AIHEALTH_GATE=0` skips that check.
