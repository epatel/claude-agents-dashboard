# Testing Guide

> **Load when**: adding or modifying tests; deciding which suite to put a new test in.
> **Skip when**: writing production code with no test changes.

## Running Tests

```bash
./run-tests.sh              # Run all 1273 tests
./run-tests.sh tests/smoke/ # Smoke tests only
./run-tests.sh -k "test_cancel" # Filter by name
./run-tests.sh -v --tb=long # Verbose with full tracebacks
```

The script creates a venv if needed and runs `pytest`. Tests use `pytest-asyncio` in auto mode. Database has 30 migrations (001–030).

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
│   │   ├── test_default_model_024.py   # Migration 024 default-model bump (4 tests)
│   │   ├── test_use_chrome_025.py      # Migration 025 use_chrome column (4 tests)
│   │   ├── test_api_error_status_026.py # Migration 026 api_error_status column (4 tests)
│   │   ├── test_remove_advisor_027.py  # Migration 027 strip +advisor suffix (5 tests)
│   │   ├── test_graphify_config_028.py # Migration 028 graphify config (3 tests)
│   │   ├── test_enabled_skills_029.py  # Migration 029 enabled_skills column (3 tests)
│   │   └── test_ollama_load_claude_md_030.py # Migration 030 ollama_load_claude_md column (3 tests)
│   ├── test_allowed_commands.py       # Command filter + access MCP (26 tests)
│   ├── test_annotation_prompt.py      # Annotation prompt formatting (5 tests)
│   ├── test_annotation_summary.py     # Annotation summary generation (2 tests)
│   ├── test_app.py                    # FastAPI app and middleware (26 tests)
│   ├── test_create_todo_autostart.py  # Todo creation with auto-start (21 tests)
│   ├── test_database_service.py       # DatabaseService CRUD (62 tests)
│   ├── test_diff_mixing.py           # Diff isolation between items (6 tests)
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
│   ├── test_mcp_tool_servers.py      # MCP tool server tests (60 tests)
│   ├── test_mini_mcp.py             # Mini-MCP server protocol (11 tests)
│   ├── test_notification_service.py  # WebSocket broadcasting (41 tests)
│   ├── test_path_validation.py       # Path traversal prevention (14 tests)
│   ├── test_routes.py               # HTTP endpoint tests (102 tests)
│   ├── test_base.py                 # AbstractAgentSession contract (4 tests)
│   ├── test_kimi_board_mcp.py       # Kimi board-tools stdio MCP proxy (9 tests)
│   ├── test_kimi_session.py         # KimiAgentSession over ACP (experimental) (58 tests)
│   ├── test_profiles.py             # Provider profiles + Kimi/Ollama routing (22 tests)
│   ├── test_session.py              # ClaudeAgentSession SDK wrapper (96 tests)
│   ├── test_session_service.py      # SessionService lifecycle + provider routing (54 tests)
│   ├── test_skills_service.py       # SkillsService install/browse/discover (11 tests)
│   ├── test_use_chrome.py           # Per-task Chrome integration (17 tests)
│   ├── test_websocket.py            # WebSocket rate limiting (45 tests)
│   └── test_workflow_service.py     # WorkflowService transitions (114 tests)
├── integration/
│   └── test_orchestrator_lifecycle.py  # Full agent workflow (14 tests)
└── README.md
```

## Test Categories

### Smoke Tests (20 tests)
Quick checks that core components work:
- Database connection and CRUD
- Module imports (core, web, git)
- Migration runner initialization
- Requirements and config validation
- Multi-repo workspace detection and sibling repo wiring

### Unit Tests — Domain & Repository Layer (100 tests)
- **ItemState FSM** (66 tests): The 13 reachable item states, events, transition rules, and `(column_name, status)` encoding round-trips
- **ItemRepository** (25 tests): Read APIs, `transition()`, `update_fields()`, `move_item`, `_WRITABLE_ITEM_COLUMNS` enforcement
- **EpicRepository** (9 tests): CRUD facade and `_WRITABLE_EPIC_COLUMNS` enforcement (replaces the old `ALLOWED_EPIC_COLUMNS` whitelist that lived in `database_service.py`)

### Unit Tests — Service Layer (283 tests)
- **WorkflowService** (108 tests): State transitions (driven through the `ItemState` FSM), agent lifecycle, merge conflict resolution, dependency auto-start, WIP-limit queueing, pause/resume, callback factories, clarification context plumbing, post-merge graph refresh
- **DatabaseService** (62 tests): CRUD operations, item dependencies, clarification context column (column whitelisting moved into the repositories)
- **SessionService** (49 tests): Session lifecycle, commit messages, plugin parsing (incl. enabled-skill plugins), SDK wrapper
- **NotificationService** (41 tests): WebSocket broadcasting, tool formatting, event types
- **GraphService** (12 tests): graphify build/refresh/query/status, version detection, cost tracking
- **SkillsService** (11 tests): library install/list/remove, browse Anthropic source, multi-skill repo discovery, spec parsing, gitignore management

### Unit Tests — Web Layer (247 tests)
- **Routes** (110 tests): HTTP endpoints for items, review, epics, shortcuts, config, stats, search, item detail, clarification context retrieval, `/api/graphify/*`, `/api/skills/*`
- **File Routes** (66 tests): Path validation, secret detection, .browserhidden, language mapping, directory scanning, file content
- **WebSocket** (45 tests): Connection management, rate limiting, dead-connection cleanup
- **App** (26 tests): FastAPI factory, middleware, CORS, security headers, lifespan

### Unit Tests — Git Layer (90 tests)
- **Git Operations** (70 tests): Diff generation, merge, commit, path validation, timeout handling
- **Git Worktree** (15 tests): Worktree create/cleanup, base branch tracking
- **Git Timeout** (5 tests): Timeout configuration and recovery

### Unit Tests — Agent Tools (105 tests)
- **MCP Tool Servers** (60 tests): Tool server creation, invocation, request/response flow, `ask_user` context field passthrough
- **Allowed Commands** (26 tests): Command filter hook, shell operator rejection, YOLO mode bypass, runtime approval persistence
- **graph_query tool** (10 tests): Read-only knowledge-graph MCP tool server
- **Kimi board-tools MCP proxy** (9 tests): stdio subprocess against a stub dashboard API — tools list, HTTP proxying, repo env, error resilience

### Unit Tests — Session (180 tests)
- `ClaudeAgentSession` SDK wrapper, token extraction, event handling (96)
- `AbstractAgentSession` contract conformance (4)
- Provider profiles: Kimi/Ollama routing predicates, env builder, profile gate matrix, options kwargs (22)
- `KimiAgentSession` over ACP: chunk aggregation, tool-call mapping, deferred tool input, commit-message + ask_user text protocols, resume/fallback, cancel, missing-SDK hint, permission decisions + handler + force-ask env, CLAUDE.md/AGENTS.md context, board-tools MCP config, errors (58)

### Unit Tests — Migrations (51 tests)
- Apply/rollback single and multiple migrations
- Migration discovery from files
- Edge cases: malformed files, concurrent apply, long versions, empty methods
- Performance: 100-file discovery under 1 second
- Per-migration data tests: 024 default-model bump (`claude-opus-4-7` → `claude-opus-4-8`), 025 use_chrome, 026 api_error_status, 027 strip `+advisor` suffix, 028 graphify config, 029 enabled_skills, 030 ollama_load_claude_md

### Unit Tests — Infrastructure (72 tests)
- **Main** (34 tests): Server startup, port discovery, git validation
- **Manage** (24 tests): Migration CLI commands
- **Path Validation** (14 tests): Traversal prevention, null bytes, symlinks, control characters

### Unit Tests — Features (81 tests)
- **Epics** (19 tests): CRUD, progress stats, item assignment, filtering, dependencies
- **Todo Auto-start** (21 tests): Todo creation with dependency-based auto-start
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
| `test_client` | HTTPX AsyncClient for route testing |
| `mock_services` | Mocked service layer for isolated testing |

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

Use `raw_db` fixture (empty DB with only `schema_migrations` table) to avoid conflicts with app migrations:

```python
async def test_apply_migration(self, raw_db, runner):
    migration = SampleMigration001()
    await runner.apply_migration(raw_db, migration)
```

### Adding New Tests

1. Place in the appropriate directory (`unit/`, `integration/`, `smoke/`)
2. Use `@pytest.mark.unit`, `@pytest.mark.integration`, or `@pytest.mark.smoke`
3. Async tests work automatically (no `@pytest.mark.asyncio` needed)
4. Run `./run-tests.sh` to verify all tests pass

## E2E Tests

End-to-end tests live in `tests/e2e/` as `.mjs` files and run via `./run-e2e-tests.sh`:

```bash
./run-e2e-tests.sh           # Run all E2E tests
./run-e2e-tests.sh --verbose # Verbose with colored output
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
| `helpers.mjs` | Shared test utilities (`startServer`, `stopServer`, `page.evaluate` for `fetch`) | — |

The first five tests run real agent sessions against a temporary test project and consume Claude tokens. The last two are pure-HTTP regression coverage — they exercise the SM/DnD encoding and the config boundary without spawning an agent, so they're free to run.

---

**See also**: [CONVENTIONS](CONVENTIONS.md) (testing section), [DATABASE](DATABASE.md) (when adding migration tests).
