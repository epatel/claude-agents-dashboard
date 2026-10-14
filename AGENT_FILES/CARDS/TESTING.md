# Testing Guide

> **Load when**: adding or modifying tests; deciding which suite to put a new test in.
> **Skip when**: writing production code with no test changes.

## Running Tests

```bash
./run-tests.sh              # Run all 1327 tests
./run-tests.sh tests/smoke/ # Smoke tests only
./run-tests.sh -k "test_cancel" # Filter by name
./run-tests.sh -v --tb=long # Verbose with full tracebacks
```

The script creates a venv if needed, installs **both** `requirements.txt` (runtime) and `requirements-test.txt` (pytest, pytest-asyncio, pytest-cov, httpx), then runs `pytest`. Running the dashboard via `run.sh` installs only the runtime file, so test deps stay out of an app-only venv — a new test dependency goes in `requirements-test.txt`. Tests use `pytest-asyncio` in auto mode. Database has 31 migrations (001–031).

## Test Structure

```
tests/
├── conftest.py                         # Shared fixtures
├── smoke/
│   ├── test_basic_functionality.py     # Imports, DB, config checks (12 tests)
│   └── test_multi_repo.py              # Multi-repo workspace detection (8 tests)
├── unit/
│   ├── migrations/
│   │   ├── test_migration_runner.py    # Migration up/down/status (14 tests)
│   │   ├── test_migration_edge_cases.py # Edge cases, discovery (14 tests)
│   │   ├── test_default_model_024.py   # Migration 024 default-model bump (3 tests)
│   │   ├── test_use_chrome_025.py      # Migration 025 use_chrome column (4 tests)
│   │   ├── test_api_error_status_026.py # Migration 026 api_error_status column (4 tests)
│   │   ├── test_remove_advisor_027.py  # Migration 027 strip +advisor suffix (5 tests)
│   │   ├── test_graphify_config_028.py # Migration 028 graphify config (3 tests)
│   │   ├── test_enabled_skills_029.py  # Migration 029 enabled_skills column (3 tests)
│   │   ├── test_ollama_load_claude_md_030.py # Migration 030 ollama_load_claude_md column (3 tests)
│   │   └── test_default_model_031.py   # Migration 031 default-model bump to Opus 5 (5 tests)
│   ├── test_allowed_commands.py       # Command filter + access MCP (26 tests)
│   ├── test_annotation_prompt.py      # Annotation prompt formatting (5 tests)
│   ├── test_annotation_summary.py     # Annotation summary generation (2 tests)
│   ├── test_app.py                    # FastAPI app and middleware (26 tests)
│   ├── test_create_todo_autostart.py  # Todo creation with auto-start (23 tests)
│   ├── test_database_service.py       # DatabaseService CRUD (62 tests)
│   ├── test_diff_mixing.py           # Diff isolation between items (6 tests)
│   ├── test_epic_plan_path.py        # Epic-scoped shared plan path (5 tests)
│   ├── test_epic_repository.py       # EpicRepository facade (9 tests)
│   ├── test_epics.py                 # Epic CRUD, progress, assignment (19 tests)
│   ├── test_file_routes.py           # File browser routes (66 tests)
│   ├── test_git_operations.py        # Git diff, merge, commit (70 tests)
│   ├── test_git_timeout.py           # Git timeout handling (5 tests)
│   ├── test_git_worktree.py          # Worktree create/cleanup (15 tests)
│   ├── test_graph_query_tool.py      # graph_query MCP tool server (10 tests)
│   ├── test_graph_service.py         # GraphService build/refresh/query/status (12 tests)
│   ├── test_item_repository.py       # ItemRepository facade + transitions (25 tests)
│   ├── test_item_state.py            # ItemState FSM: states, events, encoding (66 tests)
│   ├── test_main.py                  # Server startup, port discovery (34 tests)
│   ├── test_manage.py                # Migration CLI commands (24 tests)
│   ├── test_mcp_tool_servers.py      # MCP tool server tests (67 tests)
│   ├── test_mini_mcp.py             # Mini-MCP server protocol (11 tests)
│   ├── test_model_catalog.py        # Model feed fetch, parsing, fallbacks (14 tests)
│   ├── test_notification_service.py  # WebSocket broadcasting (41 tests)
│   ├── test_path_validation.py       # Path traversal prevention (14 tests)
│   ├── test_peek_worktree.py        # peek_worktree tool, git reads, rendering (23 tests)
│   ├── test_routes.py               # HTTP endpoint tests (116 tests)
│   ├── test_base.py                 # AbstractAgentSession contract (4 tests)
│   ├── test_kimi_board_mcp.py       # Kimi board-tools stdio MCP proxy (12 tests)
│   ├── test_kimi_session.py         # KimiAgentSession over ACP (experimental) (57 tests)
│   ├── test_profiles.py             # Provider profiles + Kimi/Ollama routing (23 tests)
│   ├── test_review_agent.py         # Auto-review session options (3 tests)
│   ├── test_session.py              # ClaudeAgentSession SDK wrapper (98 tests)
│   ├── test_session_service.py      # SessionService lifecycle + provider routing (54 tests)
│   ├── test_skills_service.py       # SkillsService install/browse/discover (11 tests)
│   ├── test_use_chrome.py           # Per-task Chrome integration (17 tests)
│   ├── test_websocket.py            # WebSocket rate limiting (45 tests)
│   └── test_workflow_service.py     # WorkflowService transitions (115 tests)
├── integration/
│   └── test_orchestrator_lifecycle.py  # Full agent workflow (14 tests)
├── e2e/                                # Node + Playwright, spawns real agents
│   ├── helpers.mjs                     # startServer/stopServer, runAgentTask, pass/fail
│   └── test_*.mjs                      # 7 E2E tests (see the E2E section below)
└── README.md
```

## Test Categories

**1327 total** = 20 smoke + 1293 unit + 14 integration. The ten `Unit Tests — …` buckets below partition those 1293 exactly; if you add a test file, put it in a bucket and update both numbers, or the totals stop reconciling. (E2E tests are counted separately — they are Node, not pytest.)

### Smoke Tests (20 tests)
Quick checks that core components work:
- Database connection and CRUD
- Module imports (core, web, git)
- Migration runner initialization
- Requirements and config validation
- Multi-repo workspace detection and sibling repo wiring

### Unit Tests — Domain & Repository Layer (100 tests)
- **ItemState FSM** (66 tests): The 13 reachable item states, events, transition rules, and `(column_name, status)` encoding round-trips
- **ItemRepository** (25 tests): Read APIs, `transition()`, `update_fields()`, `move_to_column()`, `_WRITABLE_ITEM_COLUMNS` enforcement
- **EpicRepository** (9 tests): CRUD facade and `_WRITABLE_EPIC_COLUMNS` enforcement (replaces the old `ALLOWED_EPIC_COLUMNS` whitelist that lived in `database_service.py`)

### Unit Tests — Service Layer (295 tests)
- **WorkflowService** (115 tests): State transitions (driven through the `ItemState` FSM), agent lifecycle, merge conflict resolution, dependency auto-start, WIP-limit queueing, pause/resume, callback factories, clarification context plumbing, post-merge graph refresh
- **DatabaseService** (62 tests): CRUD operations, item dependencies, clarification context column (column whitelisting moved into the repositories)
- **SessionService** (54 tests): Session lifecycle, commit messages, plugin parsing (incl. enabled-skill plugins), SDK wrapper
- **NotificationService** (41 tests): WebSocket broadcasting, tool formatting, event types
- **GraphService** (12 tests): graphify build/refresh/query/status, version detection, cost tracking
- **SkillsService** (11 tests): library install/list/remove, browse Anthropic source, multi-skill repo discovery, spec parsing, gitignore management

### Unit Tests — Web Layer (253 tests)
- **Routes** (116 tests): HTTP endpoints for items, review, epics, shortcuts, config, stats, search, item detail, clarification context retrieval, `/api/graphify/*`, `/api/skills/*`
- **File Routes** (66 tests): Path validation, secret detection, .browserhidden, language mapping, directory scanning, file content
- **WebSocket** (45 tests): Connection management, rate limiting, dead-connection cleanup
- **App** (26 tests): FastAPI factory, middleware, CORS, security headers, lifespan

### Unit Tests — Git Layer (90 tests)
- **Git Operations** (70 tests): Diff generation, merge, commit, path validation, timeout handling
- **Git Worktree** (15 tests): Worktree create/cleanup, base branch tracking
- **Git Timeout** (5 tests): Timeout configuration and recovery

### Unit Tests — Agent Tools (138 tests)
- **MCP Tool Servers** (67 tests): Tool server creation, invocation, request/response flow, `ask_user` context field passthrough
- **Allowed Commands** (26 tests): Command filter hook, shell operator rejection, YOLO mode bypass, runtime approval persistence
- **peek_worktree** (23 tests): cross-worktree tool, the `GitService` reads behind it, overlap flagging and rendering
- **graph_query tool** (10 tests): Read-only knowledge-graph MCP tool server
- **Kimi board-tools MCP proxy** (12 tests): stdio subprocess against a stub dashboard API — tools list, agent-todos proxying (requires/autostart), error resilience

### Unit Tests — Session (185 tests)
- `ClaudeAgentSession` SDK wrapper, token extraction, event handling, `verbatim_prompts` (98)
- Auto-review session (`review_agent.run_auto_review`): `ClaudeAgentOptions` on both
  the Claude and Ollama branches, prompt passed through unmodified (3)
- `AbstractAgentSession` contract conformance (4)
- Provider profiles: Kimi/Ollama routing predicates, env builder, profile gate matrix, options kwargs (23)
- `KimiAgentSession` over ACP: chunk aggregation, tool-call mapping, deferred tool input, commit-message + ask_user text protocols, resume/fallback, cancel, missing-SDK hint, permission decisions + handler + force-ask env, CLAUDE.md/AGENTS.md context, board-tools MCP config, errors (57)

### Unit Tests — Migrations (58 tests)
- Apply/rollback single and multiple migrations
- Migration discovery from files
- Edge cases: malformed files, concurrent apply, long versions, empty methods
- Performance: 100-file discovery under 1 second
- Per-migration data tests: 024 default-model bump (`claude-opus-4-7` → `claude-opus-4-8`), 025 use_chrome, 026 api_error_status, 027 strip `+advisor` suffix, 028 graphify config, 029 enabled_skills, 030 ollama_load_claude_md, 031 default-model bump (`claude-opus-4-8` → `claude-opus-5`, incl. the `[1m]` variant)

### Unit Tests — Infrastructure (72 tests)
- **Main** (34 tests): Server startup, port discovery, git validation
- **Manage** (24 tests): Migration CLI commands
- **Path Validation** (14 tests): Traversal prevention, null bytes, symlinks, control characters

### Unit Tests — Config & Catalog (19 tests)
- **Model catalog** (14 tests): feed fetch and parsing, per-provider filtering, `[1m]` synthesis, offline fallback to the bundled lists
- **Epic plan path** (5 tests): epic-scoped shared-plan path resolution

### Unit Tests — Features (83 tests)
- **Epics** (19 tests): CRUD, progress stats, item assignment, filtering, dependencies
- **Todo Auto-start** (23 tests): Todo creation with dependency-based auto-start
- **use_chrome** (17 tests): Per-task Chrome browser integration
- **Mini-MCP** (11 tests): Example MCP server protocol compliance
- **Diff Mixing** (6 tests): Diff isolation between concurrent items, base commit pinning
- **Annotation Prompt** (5 tests): Prompt formatting for agents
- **Annotation Summary** (2 tests): Summary text generation

### Integration Tests (14 tests)
Tests the full orchestrator lifecycle through the service layer:
- **Happy path**: start → complete → approve → done
- **Failure**: agent error → failed status
- **Cancellation**: cancel running agent
- **Review loop**: complete → request changes → restart
- **Review cancel**: discard and clean up worktree
- **Retry**: restart failed agent
- **Merge conflicts**: abort and set resolving status
- **Clarification**: async prompt → user response → resume
- **Commit messages**: agent sets message → used in merge
- **Token tracking**: usage saved to database
- **Concurrency**: 3 parallel agents
- **Worktree errors**: graceful failure handling
- **Rapid cancel/restart**: no orphaned state
- **Shutdown**: clean up all active agents

## Key Fixtures (conftest.py)

| Fixture | Description |
|---------|-------------|
| `temp_dir` | Temporary directory, auto-cleaned |
| `test_db` | Initialized SQLite with full app schema |
| `test_db_connection` | Direct DB connection |
| `migration_runner` | MigrationRunner with temp directory |
| `mock_websocket_manager` | Mocked ConnectionManager |
| `test_orchestrator` | Full orchestrator with git-initialized temp project |
| `test_item` | Pre-created item in the test database |
| `mock_git_operations` | Mocked git/worktree functions |
| `test_item_data` | Plain dict of item fields, for building items in a test |

## Writing Tests

### Mocking the Service Layer

The orchestrator delegates to services. Integration tests mock at the service boundary:

```python
# Mock session start (prevents real subprocess)
with patch.object(orchestrator.session_service, 'start_session_task', new_callable=AsyncMock):
    await orchestrator.start_agent(item_id)

# Simulate completion via the session's on_complete callback
session = orchestrator.session_service.sessions.get(item_id)
await session.on_complete(AgentResult(success=True, session_id="test"))

# Mock git operations
with patch.object(orchestrator.git_service, 'merge_agent_work',
                  new_callable=AsyncMock, return_value=(True, "ok")):
    await orchestrator.approve_item(item_id)
```

### Migration Tests

`raw_db` (an empty DB with only the `schema_migrations` table) and `runner` avoid conflicts with the app migrations — but they are **module-local** fixtures, defined in both `test_migration_edge_cases.py` and `test_migration_runner.py`. There is no `tests/unit/migrations/conftest.py`, so a new file must copy them (or promote them to a shared conftest):

```python
async def test_apply_migration(self, raw_db, runner):
    migration = SampleMigration001()
    await runner.apply_migration(raw_db, migration)
```

### Adding New Tests

1. Place in the appropriate directory (`unit/`, `integration/`, `smoke/`)
2. Markers (`@pytest.mark.unit` / `integration` / `smoke`) are declared in `pytest.ini` but applied to only a minority of files — `pytest -m unit` collects ~94 of 1293. Select by path (`./run-tests.sh tests/unit/`), not by marker.
3. Async tests work automatically (no `@pytest.mark.asyncio` needed)
4. Run `./run-tests.sh` to verify all tests pass

## E2E Tests

End-to-end tests live in `tests/e2e/` as `.mjs` files and run via `./run-e2e-tests.sh`:

```bash
./run-e2e-tests.sh              # Run all E2E tests
./run-e2e-tests.sh --verbose    # Stream server and agent output
./run-e2e-tests.sh --model <id> # Override the model under test
```

| Test File | Focus | Spawns agent? |
|-----------|-------|---------------|
| `test_append_readme.mjs` | Agent creates/modifies a file end-to-end | yes |
| `test_clarification.mjs` | Agent asks question, user responds, agent continues | yes |
| `test_merge_conflict.mjs` | Merge conflict detection and auto-resolution | yes |
| `test_allowed_tools.mjs` | Optional built-in tool access request flow | yes |
| `test_mini_mcp.mjs` | External MCP server integration via stdio | yes |
| `test_state_machine_dnd.mjs` | DnD produces SM-canonical `(column, status)` encoding (5 cases: todo→doing yields `("doing", null)`; cancelled-in-todo→doing also yields `("doing", null)`; post-DnD encoding is SM-readable; move-to-done clears `worktree_path` and stamps `done_at`; reorder preserves status) | no (pure HTTP) |
| `test_config_roundtrip.mjs` | Phase 3 `AgentConfig` boundary contract — GET returns typed lists/dicts; PUT arrays/objects round-trip across SQLite TEXT; legacy JSON-string input is parsed by the pre-validator (4 steps) | no (pure HTTP) |
| `helpers.mjs` | Shared utilities: `startServer` / `stopServer` (or reuse an external one via `E2E_PORT`), `runAgentTask`, `deleteItem`, `printWorkLog`, `pass` / `fail` / `warn` | — |

The first five tests run real agent sessions against a temporary test project and consume Claude tokens. The last two are pure-HTTP regression coverage — they exercise the SM/DnD encoding and the config boundary without spawning an agent, so they're free to run.

**Prerequisites and environment:** the runner needs Node.js and npm, and `npm install`s Playwright on demand. It creates and reuses a scratch project at `./claude-agents-dashboard-e2e-test` next to the current directory — it must never be pointed at this repo.

| Variable | Effect |
|---|---|
| `E2E_RESET` | `yes` / `no` / `ask` — whether to reset the scratch project between runs. Defaults to keeping it when stdin is not a TTY. |
| `E2E_PORT` | Run the tests against an already-running server instead of starting one. |
| `E2E_MODEL` | Model under test (what `--model` sets). |

For coverage across an E2E run use `./run-e2e-coverage.sh`, which starts the server under `coverage run`, sets `E2E_PORT`, and shuts it down via `POST /api/shutdown`. `./run-coverage.sh` is the pytest-only equivalent.

---

**See also**: [CONVENTIONS](CONVENTIONS.md) (testing section), [DATABASE](DATABASE.md) (when adding migration tests).
