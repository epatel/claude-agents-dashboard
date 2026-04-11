# Agent Dashboard Test Suite

This directory contains the automated test suite (837 tests) for the Agent Dashboard application, covering orchestrator lifecycle, database migrations (13 migrations), security, git operations, services, routes, WebSocket, sessions, and agent tools.

## Test Structure

```
tests/
├── conftest.py                                   # Shared fixtures and test configuration
├── unit/                                         # Unit tests (fast, isolated)
│   ├── migrations/
│   │   ├── test_migration_runner.py             # Core migration functionality (14 tests)
│   │   └── test_migration_edge_cases.py         # Edge cases and error scenarios (14 tests)
│   ├── test_advisor.py                          # Advisor logic (13 tests)
│   ├── test_allowed_commands.py                 # Command filter + access MCP tool (26 tests)
│   ├── test_annotation_prompt.py                # Annotation prompt formatting (5 tests)
│   ├── test_annotation_summary.py               # Annotation summary generation (2 tests)
│   ├── test_app.py                              # FastAPI app creation and middleware (23 tests)
│   ├── test_create_todo_autostart.py            # Todo creation with auto-start (13 tests)
│   ├── test_database_service.py                 # DatabaseService CRUD operations (47 tests)
│   ├── test_diff_mixing.py                      # Diff isolation between items (6 tests)
│   ├── test_epics.py                            # Epic CRUD, progress, item assignment (19 tests)
│   ├── test_file_routes.py                      # File browser routes (66 tests)
│   ├── test_git_operations.py                   # Git diff, merge, commit operations (67 tests)
│   ├── test_git_timeout.py                      # Git timeout handling (5 tests)
│   ├── test_git_worktree.py                     # Git worktree create/cleanup (15 tests)
│   ├── test_main.py                             # Server startup and port discovery (34 tests)
│   ├── test_manage.py                           # Migration CLI commands (24 tests)
│   ├── test_mcp_tool_servers.py                 # MCP tool server creation and invocation (50 tests)
│   ├── test_mini_mcp.py                         # Mini-MCP server protocol tests (11 tests)
│   ├── test_notification_service.py             # WebSocket broadcasting (41 tests)
│   ├── test_path_validation.py                  # Path traversal prevention (14 tests)
│   ├── test_routes.py                           # HTTP endpoint tests (69 tests)
│   ├── test_session.py                          # AgentSession SDK wrapper (64 tests)
│   ├── test_session_service.py                  # SessionService lifecycle (54 tests)
│   ├── test_websocket.py                        # WebSocket connection and rate limiting (45 tests)
│   └── test_workflow_service.py                 # WorkflowService state transitions (70 tests)
├── integration/                                  # Integration tests (slower, multi-component)
│   └── test_orchestrator_lifecycle.py           # Complete agent lifecycle testing (14 tests)
├── smoke/                                        # Smoke tests (basic functionality)
│   └── test_basic_functionality.py              # Quick regression checks (12 tests)
└── README.md                                     # This file
```

## Test Coverage by Area

### 1. Service Layer (212 tests)
- **WorkflowService** (70 tests) — State transitions, agent lifecycle, merge conflict resolution, dependency auto-start, callback factories
- **DatabaseService** (47 tests) — CRUD operations, item dependencies, column whitelist validation
- **SessionService** (54 tests) — Session lifecycle, commit messages, plugin parsing, SDK wrapper
- **NotificationService** (41 tests) — WebSocket broadcasting, tool formatting, event types

### 2. Web Layer (203 tests)
- **Routes** (69 tests) — HTTP endpoints for items, review, epics, shortcuts, config, stats, search
- **File Routes** (66 tests) — File browser path validation, secret detection, .browserhidden, language mapping, directory scanning
- **WebSocket** (45 tests) — Connection management, rate limiting, dead-connection cleanup
- **App** (23 tests) — FastAPI factory, middleware, CORS, security headers, lifespan

### 3. Git Layer (87 tests)
- **Git Operations** (67 tests) — Diff generation, merge, commit, path validation, timeout handling
- **Git Worktree** (15 tests) — Worktree create/cleanup, base branch tracking
- **Git Timeout** (5 tests) — Timeout configuration and recovery

### 4. Agent Tools (153 tests)
- **MCP Tool Servers** (50 tests) — Tool server creation, invocation, request/response flow
- **Allowed Commands** (26 tests) — Command filter hook, shell operator rejection, YOLO mode bypass
- **Advisor** (13 tests) — Agent advisor logic
- **Session** (64 tests) — AgentSession SDK wrapper, token extraction, event handling

### 5. Features (56 tests)
- **Epics** (19 tests) — CRUD, progress stats, item assignment, filtering, dependencies
- **Todo Auto-start** (13 tests) — Todo creation with dependency-based auto-start
- **Diff Mixing** (6 tests) — Diff isolation between concurrent items
- **Annotation Summary** (2 tests) — Summary text generation
- **Annotation Prompt** (5 tests) — Prompt formatting for agents
- **Mini-MCP** (11 tests) — Example MCP server protocol compliance

### 6. Infrastructure (112 tests)
- **Migrations** (28 tests) — Runner, up/down, discovery, edge cases
- **Main** (34 tests) — Server startup, port discovery, git validation
- **Manage** (24 tests) — Migration CLI commands
- **Path Validation** (14 tests) — Traversal prevention, null bytes, symlinks
- **Smoke** (12 tests) — Imports, DB basics, config validation

### 7. Orchestrator Lifecycle (Integration, 14 tests)
Tests the complete agent workflow end-to-end:
- ✅ Start → Complete → Approve → Done
- ✅ Failure, cancellation, review loop, merge conflicts
- ✅ Clarification flow, commit messages, token tracking
- ✅ Concurrency (3 parallel agents), rapid cancel/restart, shutdown

### 8. E2E Tests
**Directory: `tests/e2e/`** — Real agent sessions against a test project:
- ✅ **Append README**: Agent creates/modifies a file end-to-end
- ✅ **Clarification**: Agent asks a question, receives user response, continues
- ✅ **Merge conflict**: Agent handles merge conflict auto-resolution
- ✅ **Allowed tools**: Agent requests and uses optional built-in tools
- ✅ **Mini-MCP**: External MCP server integration via stdio

Run with: `./run-e2e-tests.sh` (supports `--verbose` flag for colored output)

## Running Tests

### Quick Start
```bash
# Run all 837 tests
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