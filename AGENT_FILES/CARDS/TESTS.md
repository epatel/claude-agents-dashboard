# Tests

`tests/` is split into:

- `unit/` — Python unit tests, plus `unit/migrations/` for migration tests
- `integration/` — orchestrator lifecycle
- `smoke/` — basic functionality + multi-repo
- `e2e/` — Node `.mjs` Playwright/HTTP scripts driven by `run-e2e-tests.sh`

**Total**: 983 tests.

```bash
./run-tests.sh                      # All tests
./run-tests.sh tests/smoke/         # Smoke tests only
./run-tests.sh -k "test_cancel"     # Filter by name
./run-e2e-tests.sh                  # E2E tests
```
