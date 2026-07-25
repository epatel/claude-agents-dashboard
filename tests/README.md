# Agent Dashboard Test Suite

This directory contains the automated test suite (1281 tests across 47 Python test files plus `conftest.py`, plus 7 Node Playwright `.mjs` E2E tests under `e2e/`) for the Agent Dashboard application, covering orchestrator lifecycle, database migrations (31 migrations), security, git operations, services (including the graphify `GraphService` and the `SkillsService`), routes, WebSocket, sessions, agent tools, the `ItemState` finite state machine, item/epic repositories, and multi-repo workspace mode.

## Test Structure

```
tests/
├── conftest.py                                   # Shared fixtures and test configuration
├── unit/                                         # Unit tests (fast, isolated)
│   ├── migrations/
│   │   ├── test_migration_runner.py             # Core migration functionality (14 tests)
│   │   ├── test_migration_edge_cases.py         # Edge cases and error scenarios (14 tests)
│   │   ├── test_default_model_024.py            # Migration 024 default-model bump (4 tests)
│   │   ├── test_use_chrome_025.py               # Migration 025 use_chrome column (4 tests)
│   │   ├── test_api_error_status_026.py         # Migration 026 api_error_status column (4 tests)
│   │   ├── test_remove_advisor_027.py           # Migration 027 strip +advisor suffix (5 tests)
│   │   ├── test_graphify_config_028.py          # Migration 028 graphify config (3 tests)
│   │   └── test_enabled_skills_029.py           # Migration 029 enabled_skills column (3 tests)
│   ├── test_allowed_commands.py                 # Command filter + access MCP tool (26 tests)
│   ├── test_annotation_prompt.py                # Annotation prompt formatting (5 tests)
│   ├── test_annotation_summary.py               # Annotation summary generation (2 tests)
│   ├── test_app.py                              # FastAPI app creation and middleware (26 tests)
│   ├── test_create_todo_autostart.py            # Todo creation with auto-start (21 tests)
│   ├── test_database_service.py                 # DatabaseService CRUD operations (62 tests)
│   ├── test_diff_mixing.py                      # Diff isolation between items (6 tests)
│   ├── test_epic_repository.py                  # EpicRepository facade (9 tests)
│   ├── test_epics.py                            # Epic CRUD, progress, item assignment (19 tests)
│   ├── test_file_routes.py                      # File browser routes (66 tests)
│   ├── test_git_operations.py                   # Git diff, merge, commit operations (70 tests)
│   ├── test_git_timeout.py                      # Git timeout handling (5 tests)
│   ├── test_git_worktree.py                     # Git worktree create/cleanup (15 tests)
│   ├── test_graph_query_tool.py                 # graph_query MCP tool server (10 tests)
│   ├── test_graph_service.py                    # GraphService build/refresh/query/status (12 tests)
│   ├── test_item_repository.py                  # ItemRepository facade + transition()/update_fields() (25 tests)
│   ├── test_item_state.py                       # ItemState FSM: states, events, encoding (66 tests)
│   ├── test_main.py                             # Server startup and port discovery (34 tests)
│   ├── test_manage.py                           # Migration CLI commands (24 tests)
│   ├── test_mcp_tool_servers.py                 # MCP tool server creation and invocation (60 tests)
│   ├── test_mini_mcp.py                         # Mini-MCP server protocol tests (11 tests)
│   ├── test_notification_service.py             # WebSocket broadcasting (41 tests)
│   ├── test_path_validation.py                  # Path traversal prevention (14 tests)
│   ├── test_routes.py                           # HTTP endpoint tests (102 tests)
│   ├── test_session.py                          # AgentSession SDK wrapper (83 tests)
│   ├── test_session_service.py                  # SessionService lifecycle (49 tests)
│   ├── test_skills_service.py                   # SkillsService install/browse/discover/enable (11 tests)
│   ├── test_use_chrome.py                       # Per-task Chrome integration (17 tests)
│   ├── test_websocket.py                        # WebSocket connection and rate limiting (45 tests)
│   └── test_workflow_service.py                 # WorkflowService state transitions (108 tests)
├── integration/                                  # Integration tests (slower, multi-component)
│   └── test_orchestrator_lifecycle.py           # Complete agent lifecycle testing (14 tests)
├── smoke/                                        # Smoke tests (basic functionality)
│   ├── test_basic_functionality.py              # Quick regression checks (12 tests)
│   └── test_multi_repo.py                       # Multi-repo workspace detection and routing (8 tests)
└── README.md                                     # This file
```

## Test Coverage by Area

### 1. Domain & Repository Layer (100 tests)
- **ItemState FSM** (66 tests) — States, events, transitions, `from_columns`/`to_columns` encoding round-trips
- **ItemRepository** (25 tests) — Read APIs, `transition()`, `update_fields()`, `move_item`, column whitelist enforcement
- **EpicRepository** (9 tests) — CRUD facade and column whitelist enforcement

### 2. Service Layer (283 tests)
- **WorkflowService** (108 tests) — State transitions (driven through `ItemState` FSM), agent lifecycle, merge conflict resolution, dependency auto-start, WIP-limit queueing, pause/resume, callback factories, clarification context plumbing, post-merge graph refresh
- **DatabaseService** (62 tests) — CRUD operations, item dependencies, clarification context column (column whitelisting moved to the repositories)
- **SessionService** (49 tests) — Session lifecycle, commit messages, plugin parsing (incl. enabled-skill plugins), SDK wrapper
- **NotificationService** (41 tests) — WebSocket broadcasting, tool formatting, event types
- **GraphService** (12 tests) — graphify build/refresh/query/status, version detection, cost tracking
- **SkillsService** (11 tests) — library install/list/remove, browse Anthropic source, multi-skill repo discovery, spec parsing, gitignore management

### 3. Web Layer (247 tests)
- **Routes** (110 tests) — HTTP endpoints for items, review, epics, shortcuts, config, stats, search, item detail, clarification context retrieval, graphify endpoints, skills library endpoints
- **File Routes** (66 tests) — File browser path validation, secret detection, .browserhidden, language mapping, directory scanning
- **WebSocket** (45 tests) — Connection management, rate limiting, dead-connection cleanup
- **App** (26 tests) — FastAPI factory, middleware, CORS, security headers, lifespan

### 4. Git Layer (90 tests)
- **Git Operations** (70 tests) — Diff generation, merge, commit, path validation, timeout handling
- **Git Worktree** (15 tests) — Worktree create/cleanup, base branch tracking
- **Git Timeout** (5 tests) — Timeout configuration and recovery

### 5. Agent Tools (96 tests)
- **MCP Tool Servers** (60 tests) — Tool server creation, invocation, request/response flow, `ask_user` context field passthrough
- **Allowed Commands** (26 tests) — Command filter hook, shell operator rejection, YOLO mode bypass
- **graph_query tool** (10 tests) — Read-only knowledge-graph MCP tool server

### 5b. Session (83 tests)
- **AgentSession** (83 tests) — SDK wrapper, token extraction, event handling, Ollama provider env configuration

### 6. Features (81 tests)
- **Epics** (19 tests) — CRUD, progress stats, item assignment, filtering, dependencies
- **Todo Auto-start** (21 tests) — Todo creation with dependency-based auto-start
- **use_chrome** (17 tests) — Per-task Chrome browser integration
- **Mini-MCP** (11 tests) — Example MCP server protocol compliance
- **Diff Mixing** (6 tests) — Diff isolation between concurrent items
- **Annotation Prompt** (5 tests) — Prompt formatting for agents
- **Annotation Summary** (2 tests) — Summary text generation

### 7. Infrastructure (143 tests)
- **Migrations** (58 tests) — Runner, up/down, discovery, edge cases; per-migration data tests for 024 (default-model bump), 025 (use_chrome), 026 (api_error_status), 027 (remove +advisor), 028 (graphify config), 029 (enabled_skills), 031 (default-model bump to Opus 5)
- **Main** (34 tests) — Server startup, port discovery, git validation
- **Manage** (24 tests) — Migration CLI commands
- **Path Validation** (14 tests) — Traversal prevention, null bytes, symlinks
- **Smoke — Basic** (12 tests) — Imports, DB basics, config validation
- **Smoke — Multi-repo** (8 tests) — Sibling repo detection, repo path resolution, workspace mode wiring

### 8. Orchestrator Lifecycle (Integration, 14 tests)
Tests the complete agent workflow end-to-end:
- ✅ Start → Complete → Approve → Done
- ✅ Failure, cancellation, review loop, merge conflicts
- ✅ Clarification flow, commit messages, token tracking
- ✅ Concurrency (3 parallel agents), rapid cancel/restart, shutdown

### 9. E2E Tests
**Directory: `tests/e2e/`** — 7 `.mjs` test files. The first five exercise real agent sessions; the last two are pure-HTTP (no Claude session, no spend):
- ✅ **Append README** (`test_append_readme.mjs`): Agent creates/modifies a file end-to-end
- ✅ **Clarification** (`test_clarification.mjs`): Agent asks a question, receives user response, continues
- ✅ **Merge conflict** (`test_merge_conflict.mjs`): Agent handles merge conflict auto-resolution
- ✅ **Allowed tools** (`test_allowed_tools.mjs`): Agent requests and uses optional built-in tools
- ✅ **Mini-MCP** (`test_mini_mcp.mjs`): External MCP server integration via stdio
- ✅ **DnD canonicalization** (`test_state_machine_dnd.mjs`, 5 cases): Drag-and-drop produces SM-canonical `(column, status)` encoding (e.g. todo→doing yields `("doing", null)`, never the off-canon family that crashed Start before Phase 2's `move_to_column` normalization); reorder preserves status; move-to-done clears `worktree_path` and stamps `done_at`. Pure HTTP — no agent spawn.
- ✅ **AgentConfig round-trip** (`test_config_roundtrip.mjs`, 4 steps): Phase 3 boundary contract — `GET /api/config` returns typed lists/dicts (never JSON strings); arrays/objects round-trip across SQLite TEXT storage; legacy JSON-string input on `PUT` is parsed by the `field_validator(mode="before")`. Pure HTTP.

Run with: `./run-e2e-tests.sh` (supports `--verbose` flag for colored output)

Use `--model` to override the Claude model used by all E2E agents (defaults to the server's configured model):
```bash
./run-e2e-tests.sh --model claude-haiku-4-5-20251001   # cheaper/faster runs
./run-e2e-tests.sh --model claude-opus-4-8 --verbose    # combine with other flags
```

## Running Tests

### Quick Start
```bash
# Run all 1281 tests
./run-tests.sh

# Run specific test categories
./run-tests.sh tests/unit/        # Unit tests only
./run-tests.sh tests/integration/ # Integration tests
./run-tests.sh tests/smoke/       # Smoke tests

# Filter by name
./run-tests.sh -k "test_cancel"
```

### Using pytest directly
```bash
# All tests with coverage
pytest

# Specific test files
pytest tests/integration/test_orchestrator_lifecycle.py
pytest tests/unit/migrations/

# Run tests with specific markers
pytest -m unit
pytest -m integration
pytest -m smoke

# Verbose output
pytest -v

# Stop on first failure
pytest -x

# Run in parallel (requires pytest-xdist)
pip install pytest-xdist
pytest -n auto
```

### Coverage Reports
```bash
# Generate HTML coverage report
./run-tests.sh --cov=src --cov-report=html
open htmlcov/index.html
```

## Test Configuration

### pytest.ini
Key configuration settings:
- **Async Support**: `asyncio_mode = auto`
- **Coverage**: Minimum 75% coverage requirement
- **Markers**: Test categorization (unit, integration, smoke, slow)
- **Output**: Verbose reporting with durations

### Fixtures (conftest.py)
Shared test infrastructure:
- `test_db`: Temporary test database
- `test_orchestrator`: Configured orchestrator instance
- `mock_git_operations`: Mocked git operations for testing
- `test_item`: Sample test data

## Dependencies

Core testing dependencies (in requirements.txt):
- `pytest>=8.0.0` - Test framework
- `pytest-asyncio>=0.23.0` - Async test support
- `pytest-cov>=4.0.0` - Coverage reporting
- `pytest-mock>=3.12.0` - Mocking utilities

Install additional development dependencies:
```bash
pip install pytest-xdist  # Parallel test execution
pip install pytest-html   # HTML test reports
```

## Writing New Tests

### Test Categories

**Unit Tests** (`tests/unit/`):
- Fast, isolated component tests
- Mock external dependencies
- Focus on single functions/methods
- Mark with `@pytest.mark.unit`

**Integration Tests** (`tests/integration/`):
- Test multiple components together
- Real database, mocked git operations
- End-to-end workflows
- Mark with `@pytest.mark.integration`

**Smoke Tests** (`tests/smoke/`):
- Quick regression tests
- Basic functionality verification
- Fast execution for CI/CD
- Mark with `@pytest.mark.smoke`

### Example Test Structure
```python
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.unit  # or @pytest.mark.integration
class TestMyComponent:
    """Test suite for MyComponent."""

    async def test_basic_functionality(self, test_fixture):
        """Test basic functionality works correctly."""
        # Arrange
        component = MyComponent()

        # Act
        result = await component.do_something()

        # Assert
        assert result.success is True

    async def test_error_handling(self, test_fixture):
        """Test component handles errors correctly."""
        with pytest.raises(ExpectedError):
            await component.failing_operation()
```

### Best Practices

1. **Naming**: Use descriptive test names explaining what is being tested
2. **Structure**: Follow Arrange-Act-Assert pattern
3. **Isolation**: Each test should be independent
4. **Mocking**: Mock external dependencies (git, filesystem, network)
5. **Async**: Use `async def` for tests that await async operations
6. **Cleanup**: Use fixtures for setup/teardown
7. **Coverage**: Aim for high test coverage of critical paths

## CI/CD Integration

The test suite is designed for continuous integration:

```yaml
# Example GitHub Actions step
- name: Run tests
  run: ./run-tests.sh
```

## Troubleshooting

### Common Issues

**Import Errors**:
```bash
# Ensure PYTHONPATH includes src/
export PYTHONPATH="${PYTHONPATH}:$(pwd)/src"
pytest
```

**Database Issues**:
```bash
# Check test database permissions
ls -la tests/
# Ensure temp directories are writable
```

**Async Test Issues**:
```bash
# Verify pytest-asyncio is installed
pip install pytest-asyncio
# Check asyncio_mode in pytest.ini
```

### Debug Mode
```bash
# Run with debugging output
pytest -v -s --tb=long

# Run single test with debugging
pytest -v -s tests/unit/test_specific.py::TestClass::test_method
```

## Performance Monitoring

Track test performance:
```bash
# Show slowest tests
pytest --durations=10

# Profile test execution
pytest --profile

# Check memory usage
pytest --memray
```

## Contributing

When adding new features:

1. **Add tests first** (TDD approach recommended)
2. **Ensure P0 coverage** for critical functionality
3. **Run full test suite** before committing
4. **Update this README** if adding new test categories
5. **Maintain 75%+ coverage** for all new code

## Test Data Management

Test data strategy:
- **Fixtures**: Use conftest.py fixtures for reusable test data
- **Factories**: Consider factory pattern for complex test objects
- **Cleanup**: All tests use temporary directories/databases
- **Isolation**: No shared state between tests