# Testing Guide

## Running Tests

```bash
./run-tests.sh              # Run all 213 tests
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
│   ├── test_path_validation.py         # Path traversal prevention (14 tests)
│   ├── test_git_timeout.py            # Git timeout handling (5 tests)
│   ├── test_file_routes.py            # File browser routes (66 tests)
│   ├── test_allowed_commands.py       # Command filter + access MCP (26 tests)
│   ├── test_diff_mixing.py           # Diff isolation between items (6 tests)
│   ├── test_mini_mcp.py             # Mini-MCP server protocol (11 tests)
│   ├── test_epics.py               # Epic CRUD, progress, assignment (19 tests)
│   ├── test_annotation_summary.py  # Annotation summary generation (2 tests)
│   └── test_annotation_prompt.py   # Annotation prompt formatting (5 tests)
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

### Unit Tests — Migrations (28 tests)
Tests the migration runner in isolation using raw SQLite (no app schema):
- Apply/rollback single and multiple migrations
- Migration discovery from files
- Edge cases: malformed files, concurrent apply, long versions, empty methods
- Performance: 100-file discovery under 1 second

### Unit Tests — Path Validation (14 tests)
Tests `validate_file_path()` security:
- Path traversal patterns (`..`, absolute paths)
- Null bytes, control characters, Windows separators
- Symlink-aware validation
- Length limits

### Unit Tests — Git Timeout (5 tests)
Tests timeout handling in git operations:
- Default timeout configuration
- Merge-specific timeout
- Timeout abort and recovery

### Unit Tests — File Browser Routes (66 tests)
Tests `file_routes.py` endpoints:
- Path validation and security (traversal, symlinks, null bytes)
- Secret file detection and hiding
- Language/extension mapping
- Directory tree scanning with depth limits
- File content reading (text, binary, images)

### Unit Tests — Allowed Commands (26 tests)
Tests command filtering and runtime access:
- Command filter hook: allow/deny bash commands by first-word prefix
- Non-bash tools pass through without filtering
- Empty allowlist denies all bash commands
- Command access MCP tool server creation
- Permission request flow: approve saves to agent_config
- Multiple commands can be saved and retrieved
- YOLO mode bypass, runtime approval persistence
- Edge cases: empty commands, multi-word prefixes

### Unit Tests — Diff Mixing (6 tests)
Tests diff isolation between concurrent agent items:
- Independent diffs: each item only sees its own changes
- Diff during concurrent merge: diffs remain stable
- Uncommitted changes don't leak between items
- Diff after base moves forward (using base_commit pinning)
- Concurrent diff requests return correct results
- Diff while merge is in progress (race condition testing)

### Unit Tests — Mini-MCP Server (11 tests)
Tests the mini-MCP example server via stdio JSON-RPC protocol:
- Server initialization and JSON-RPC handshake
- Tool listing and invocation
- Protocol compliance (NDJSON over stdio)
- Error handling for malformed requests

### Unit Tests — Epics (19 tests)
Tests epic CRUD and item integration:
- Epic creation with title and color
- Epic listing with progress stats (item counts per column)
- Epic update (title, color, position)
- Epic deletion (nullifies epic_id on related items)
- Item-epic assignment and unassignment
- Epic filtering and board integration
- Item dependency tracking via epics

### Unit Tests — Annotation Summary (2 tests)
Tests annotation summary generation:
- Summary text generation from annotation shapes
- Empty annotation handling

### Unit Tests — Annotation Prompt (5 tests)
Tests annotation prompt formatting for agents:
- Paired annotation file grouping (original + overlay)
- Summary inclusion in agent prompts
- Multiple attachment handling
- Non-annotation file handling

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
