# Testing Guide

## Running Tests

```bash
./run-tests.sh              # Run all 837 tests
./run-tests.sh tests/smoke/ # Smoke tests only
./run-tests.sh -k "test_cancel" # Filter by name
./run-tests.sh -v --tb=long # Verbose with full tracebacks
```

The script creates a venv if needed and runs `pytest`. Tests use `pytest-asyncio` in auto mode. Database has 13 migrations.

## Test Structure

```
tests/
├── conftest.py                         # Shared fixtures
├── smoke/
│   └── test_basic_functionality.py     # Imports, DB, config checks (12 tests)
├── unit/
│   ├── migrations/
│   │   ├── test_migration_runner.py    # Migration up/down/status (14 tests)
│   │   └── test_migration_edge_cases.py # Edge cases, discovery (14 tests)
│   ├── test_advisor.py                # Advisor logic (13 tests)
│   ├── test_allowed_commands.py       # Command filter + access MCP (26 tests)
│   ├── test_annotation_prompt.py      # Annotation prompt formatting (5 tests)
│   ├── test_annotation_summary.py     # Annotation summary generation (2 tests)
│   ├── test_app.py                    # FastAPI app and middleware (23 tests)
│   ├── test_create_todo_autostart.py  # Todo creation with auto-start (13 tests)
│   ├── test_database_service.py       # DatabaseService CRUD (47 tests)
│   ├── test_diff_mixing.py           # Diff isolation between items (6 tests)
│   ├── test_epics.py                 # Epic CRUD, progress, assignment (19 tests)
│   ├── test_file_routes.py           # File browser routes (66 tests)
│   ├── test_git_operations.py        # Git diff, merge, commit (67 tests)
│   ├── test_git_timeout.py           # Git timeout handling (5 tests)
│   ├── test_git_worktree.py          # Worktree create/cleanup (15 tests)
│   ├── test_main.py                  # Server startup, port discovery (34 tests)
│   ├── test_manage.py                # Migration CLI commands (24 tests)
│   ├── test_mcp_tool_servers.py      # MCP tool server tests (50 tests)
│   ├── test_mini_mcp.py             # Mini-MCP server protocol (11 tests)
│   ├── test_notification_service.py  # WebSocket broadcasting (41 tests)
│   ├── test_path_validation.py       # Path traversal prevention (14 tests)
│   ├── test_routes.py               # HTTP endpoint tests (69 tests)
│   ├── test_session.py              # AgentSession SDK wrapper (64 tests)
│   ├── test_session_service.py      # SessionService lifecycle (54 tests)
│   ├── test_websocket.py            # WebSocket rate limiting (45 tests)
│   └── test_workflow_service.py     # WorkflowService transitions (70 tests)
├── integration/
│   └── test_orchestrator_lifecycle.py  # Full agent workflow (14 tests)
└── README.md
```

## Test Categories

### Smoke Tests (12 tests)
Quick checks that core components work:
- Database connection and CRUD
- Module imports (core, web, git)
- Migration runner initialization
- Requirements and config validation

### Unit Tests — Service Layer (212 tests)
- **WorkflowService** (70 tests): State transitions, agent lifecycle, merge conflict resolution, dependency auto-start, callback factories
- **DatabaseService** (47 tests): CRUD operations, item dependencies, column whitelist validation
- **SessionService** (54 tests): Session lifecycle, commit messages, plugin parsing, SDK wrapper
- **NotificationService** (41 tests): WebSocket broadcasting, tool formatting, event types

### Unit Tests — Web Layer (203 tests)
- **Routes** (69 tests): HTTP endpoints for items, review, epics, shortcuts, config, stats, search
- **File Routes** (66 tests): Path validation, secret detection, .browserhidden, language mapping, directory scanning, file content
- **WebSocket** (45 tests): Connection management, rate limiting, dead-connection cleanup
- **App** (23 tests): FastAPI factory, middleware, CORS, security headers, lifespan

### Unit Tests — Git Layer (87 tests)
- **Git Operations** (67 tests): Diff generation, merge, commit, path validation, timeout handling
- **Git Worktree** (15 tests): Worktree create/cleanup, base branch tracking
- **Git Timeout** (5 tests): Timeout configuration and recovery

### Unit Tests — Agent Tools (89 tests)
- **MCP Tool Servers** (50 tests): Tool server creation, invocation, request/response flow
- **Allowed Commands** (26 tests): Command filter hook, shell operator rejection, YOLO mode bypass, runtime approval persistence
- **Advisor** (13 tests): Agent advisor logic

### Unit Tests — Session (64 tests)
- AgentSession SDK wrapper, token extraction, event handling

### Unit Tests — Migrations (28 tests)
- Apply/rollback single and multiple migrations
- Migration discovery from files
- Edge cases: malformed files, concurrent apply, long versions, empty methods
- Performance: 100-file discovery under 1 second

### Unit Tests — Infrastructure (72 tests)
- **Main** (34 tests): Server startup, port discovery, git validation
- **Manage** (24 tests): Migration CLI commands
- **Path Validation** (14 tests): Traversal prevention, null bytes, symlinks, control characters

### Unit Tests — Features (56 tests)
- **Epics** (19 tests): CRUD, progress stats, item assignment, filtering, dependencies
- **Todo Auto-start** (13 tests): Todo creation with dependency-based auto-start
- **Diff Mixing** (6 tests): Diff isolation between concurrent items, base commit pinning
- **Annotation Summary** (2 tests): Summary text generation
- **Annotation Prompt** (5 tests): Prompt formatting for agents
- **Mini-MCP** (11 tests): Example MCP server protocol compliance

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

| Test File | Focus |
|-----------|-------|
| `test_append_readme.mjs` | Agent creates/modifies a file end-to-end |
| `test_clarification.mjs` | Agent asks question, user responds, agent continues |
| `test_merge_conflict.mjs` | Merge conflict detection and auto-resolution |
| `test_allowed_tools.mjs` | Optional built-in tool access request flow |
| `test_mini_mcp.mjs` | External MCP server integration via stdio |
| `helpers.mjs` | Shared test utilities |

E2E tests run real agent sessions against a temporary test project and require a running server instance.
