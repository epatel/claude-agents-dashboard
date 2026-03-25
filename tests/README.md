# Agent Dashboard Test Suite

This directory contains the automated test suite for the Agent Dashboard application, focusing on P0 priority areas: **Orchestrator lifecycle** and **Database migrations**.

## Test Structure

```
tests/
├── conftest.py                                   # Shared fixtures and test configuration
├── unit/                                         # Unit tests (fast, isolated)
│   └── migrations/
│       ├── test_migration_runner.py             # Core migration functionality
│       └── test_migration_edge_cases.py         # Edge cases and error scenarios
├── integration/                                  # Integration tests (slower, multi-component)
│   └── test_orchestrator_lifecycle.py           # Complete agent lifecycle testing
├── smoke/                                        # Smoke tests (basic functionality)
│   └── test_basic_functionality.py              # Quick regression checks
└── README.md                                     # This file
```

## P0 Priority Test Coverage

### 1. Orchestrator Lifecycle (Integration Tests)
**File: `tests/integration/test_orchestrator_lifecycle.py`**

Tests the complete agent workflow:
- ✅ **Start**: Agent startup and worktree creation
- ✅ **Complete**: Session execution and completion handling
- ✅ **Merge**: Integration with git operations and cleanup
- ✅ **Error Handling**: Failures, cancellation, conflicts
- ✅ **Review Loop**: Feedback and restart workflows
- ✅ **Concurrency**: Multiple concurrent agents

### 2. Database Migrations (Unit Tests)
**Files: `tests/unit/migrations/test_migration_runner.py`, `tests/unit/migrations/test_migration_edge_cases.py`**

Tests migration operations:
- ✅ **Up/Down**: Migration application and rollback
- ✅ **Discovery**: Migration file loading and validation
- ✅ **Status**: Migration state tracking
- ✅ **Error Handling**: Failure scenarios and recovery
- ✅ **Edge Cases**: Malformed files, concurrent access, orphaned records

## Running Tests

### Quick Start
```bash
# Run all tests
python run_tests.py all

# Run only P0 priority tests (recommended)
python run_tests.py p0

# Run specific test categories
python run_tests.py unit        # Fast unit tests only
python run_tests.py integration # Slower integration tests
python run_tests.py smoke       # Quick smoke tests
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
python run_tests.py --coverage-report

# Or with pytest directly
pytest --cov=src --cov-report=html
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
  run: |
    python run_tests.py p0
    python run_tests.py smoke

- name: Upload coverage
  uses: codecov/codecov-action@v3
  with:
    file: coverage.xml
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