# Testing Guide

## Overview

The Claude Agents Dashboard has a comprehensive automated test suite covering all critical components with prioritized test levels:

- **P0 Tests**: Core functionality (orchestrator + migrations) - Must pass
- **P1 Tests**: Extended functionality (git ops + API routes + path validation + MCP tools)
- **Unit Tests**: Fast, isolated component tests
- **Integration Tests**: Multi-component interaction tests
- **Smoke Tests**: Quick regression detection

## Test Structure

```
tests/
├── conftest.py                         # Shared fixtures and configuration
├── unit/                               # Unit tests (fast, isolated)
│   ├── migrations/
│   │   ├── test_migration_runner.py    # P0: Database migrations
│   │   └── test_migration_edge_cases.py
│   ├── test_api_routes.py              # P1: REST API endpoints
│   ├── test_git_operations.py          # P1: Git operations & worktrees
│   ├── test_path_validation.py         # P1: Security & path validation
│   ├── test_websocket_manager.py       # P1: WebSocket connections
│   └── test_git_timeout.py             # Existing timeout handling
├── integration/                        # Integration tests (slower)
│   ├── test_orchestrator_lifecycle.py  # P0: Complete agent workflow
│   └── test_mcp_tool_callbacks.py      # P1: MCP tool integration
└── smoke/                              # Smoke tests (quick validation)
    └── test_basic_functionality.py     # Basic component health checks
```

## Running Tests

### Quick Start

```bash
# Install test dependencies
pip install -r requirements-test.txt

# Run all tests
python run_tests.py all

# Run priority tests only
python run_tests.py p0    # Core functionality
python run_tests.py p1    # Extended functionality

# Run by type
python run_tests.py unit         # Fast unit tests
python run_tests.py integration  # Multi-component tests
python run_tests.py smoke        # Quick smoke tests
```

### Advanced Options

```bash
# Verbose output with coverage
python run_tests.py all -v

# Fail fast (stop on first failure)
python run_tests.py unit --fail-fast

# Parallel execution (requires pytest-xdist)
python run_tests.py all --parallel

# Generate HTML coverage report
python run_tests.py --coverage-report

# Check test dependencies
python run_tests.py --check-deps
```

## Test Coverage by Component

### P0 Priority (Must Pass)

#### ✅ Orchestrator Lifecycle (`test_orchestrator_lifecycle.py`)
- Complete agent workflow (start → complete → merge)
- Session execution and completion handling
- Error scenarios and cancellation handling
- Review feedback loop and approval process
- Merge conflict resolution
- Clarification workflow
- Token usage tracking
- Concurrent agent operations
- Shutdown and cleanup procedures

**Key Test Cases:**
- `test_complete_agent_lifecycle_success` - Full happy path
- `test_agent_lifecycle_with_failure` - Error handling
- `test_review_feedback_loop` - Human-in-the-loop workflow
- `test_merge_conflict_handling` - Git conflict resolution
- `test_concurrent_agent_operations` - Multi-agent scenarios

#### ✅ Database Migrations (`test_migration_runner.py`)
- Migration discovery and loading
- Up/down migration execution
- Migration state tracking in database
- Error handling and rollback scenarios
- Target version migrations
- Migration status reporting

**Key Test Cases:**
- `test_apply_multiple_migrations_up` - Forward migration chain
- `test_rollback_multiple_migrations_down` - Rollback chain
- `test_migration_failure_handling` - Error recovery
- `test_get_migration_status` - State reporting

### P1 Priority (Extended Functionality)

#### ✅ API Routes (`test_api_routes.py`)
- REST API endpoints for items, work log, token usage
- Request validation and error handling
- HTTP status codes and response formats
- Authentication and authorization
- Pagination and filtering
- Error response structure consistency

**Key Test Cases:**
- `test_create_item_valid_data` - Item creation
- `test_update_item_not_found` - Error handling
- `test_move_item_invalid_column` - Validation
- `test_start_agent_success` - Agent control endpoints

#### ✅ Git Operations (`test_git_operations.py`)
- Repository validation and detection
- Branch operations (create, merge, delete)
- Worktree creation and cleanup
- Timeout handling and error recovery
- Security validation (path traversal prevention)
- Concurrent operations
- Network failure simulation

**Key Test Cases:**
- `test_create_worktree_success` - Worktree management
- `test_merge_branch_conflict` - Conflict handling
- `test_git_timeout_handling` - Timeout scenarios
- `test_path_traversal_prevention` - Security

#### ✅ Path Validation (`test_path_validation.py`)
- Path traversal attack prevention
- File system boundary enforcement
- Input sanitization and validation
- Symbolic link traversal prevention
- Null byte injection prevention
- Command injection prevention
- Safe file operations

**Key Test Cases:**
- `test_basic_path_traversal_patterns` - Attack prevention
- `test_directory_boundary_enforcement` - Sandbox security
- `test_filename_length_validation` - Input limits
- `test_atomic_file_operations` - Data integrity

#### ✅ MCP Tool Callbacks (`test_mcp_tool_callbacks.py`)
- Agent session MCP tool integration
- Callback handling and response processing
- Tool permission and security validation
- Error recovery and timeout handling
- Concurrent tool execution
- State management across calls

**Key Test Cases:**
- `test_clarification_tool_callback` - User interaction
- `test_file_operation_tool_callbacks` - File operations
- `test_mcp_tool_permission_validation` - Security
- `test_concurrent_mcp_tool_calls` - Performance

#### ✅ WebSocket Manager (`test_websocket_manager.py`)
- Connection lifecycle management
- Message broadcasting and routing
- Error handling and reconnection
- Real-time updates and notifications
- Connection health monitoring
- Selective message delivery

**Key Test Cases:**
- `test_message_broadcasting` - Multi-client updates
- `test_broadcast_with_failed_connection` - Error resilience
- `test_connection_health_check` - Connection monitoring
- `test_large_message_handling` - Performance

### Smoke Tests

#### ✅ Basic Functionality (`test_basic_functionality.py`)
- Database connectivity
- Component initialization
- Module imports
- Configuration validation
- Basic CRUD operations

## Test Infrastructure

### Fixtures (`conftest.py`)

- `test_db` - Isolated test database with migrations
- `test_orchestrator` - Configured orchestrator instance
- `mock_git_operations` - Git operation mocking
- `temp_dir` - Temporary directory for file operations
- `test_item` - Sample database item for testing

### Configuration (`pytest.ini`)

- Async test support with `asyncio_mode = auto`
- Test discovery patterns
- Marker definitions for test categorization
- Duration reporting for performance monitoring

### Test Runner (`run_tests.py`)

- Multiple test suite configurations
- Coverage reporting
- Parallel execution support
- Dependency validation
- Exit code handling

## Performance Testing

### Benchmarking
```bash
# Run with benchmark markers
pytest -m benchmark tests/

# Performance profiling
python -m cProfile -o profile_output run_tests.py unit
```

### Load Testing
```bash
# Concurrent operations testing
pytest tests/integration/test_orchestrator_lifecycle.py::TestOrchestratorConcurrency -v

# WebSocket connection stress testing
pytest tests/unit/test_websocket_manager.py -k "concurrent" -v
```

## Security Testing

### Static Analysis
```bash
# Security vulnerability scanning
bandit -r src/
safety check -r requirements.txt
```

### Dynamic Testing
```bash
# Path validation security tests
pytest tests/unit/test_path_validation.py::TestPathTraversalPrevention -v

# Git security validation
pytest tests/unit/test_git_operations.py::TestGitSecurityValidation -v
```

## Coverage Reports

### Generate Coverage
```bash
# HTML report
python run_tests.py --coverage-report

# Terminal report
pytest --cov=src --cov-report=term-missing tests/

# XML report for CI
pytest --cov=src --cov-report=xml tests/
```

### Coverage Targets
- **Overall**: >90% line coverage
- **Critical paths**: 100% coverage (orchestrator, migrations)
- **API endpoints**: >95% coverage
- **Security functions**: 100% coverage

## Continuous Integration

### Pre-commit Hooks
```bash
# Install pre-commit hooks
pre-commit install

# Run hooks manually
pre-commit run --all-files
```

### CI Pipeline
```yaml
# .github/workflows/tests.yml example
- name: Run P0 Tests
  run: python run_tests.py p0

- name: Run P1 Tests
  run: python run_tests.py p1

- name: Generate Coverage
  run: python run_tests.py --coverage-report
```

## Troubleshooting

### Common Issues

1. **Database Locked**: Ensure proper cleanup in test teardown
2. **Git Operations Fail**: Check git configuration in test environment
3. **Timeout Errors**: Increase timeouts for slower CI environments
4. **Permission Errors**: Verify test directory permissions

### Debug Mode
```bash
# Run with debugging
pytest --pdb tests/unit/test_specific.py::test_failing_case

# Verbose async debugging
pytest -s -v --tb=long tests/integration/
```

### Test Data
All test data is generated dynamically or uses temporary directories to ensure test isolation and repeatability.

## Contributing

When adding new functionality:

1. **Add P0 tests** for critical functionality
2. **Add P1 tests** for extended features
3. **Update fixtures** as needed in conftest.py
4. **Run full test suite** before committing
5. **Maintain >90% coverage** for new code

### Test Naming Convention
- `test_<functionality>_success` - Happy path
- `test_<functionality>_failure` - Error conditions
- `test_<functionality>_edge_case` - Boundary conditions
- `test_<functionality>_security` - Security scenarios