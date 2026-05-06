# Overview

Standalone scrum board that orchestrates Claude agents working on a **separate target project** (or a workspace of sibling git repos in multi-repo mode). Server code lives here; data directory (`agents-lab/`) is created in the target project / workspace root.

## Running

```bash
./run.sh /path/to/target-project    # Single-repo mode — creates venv, installs deps, starts server (Python 3.12+)
./run.sh /path/to/workspace-folder  # Multi-repo mode — workspace must contain ≥1 sibling git repos
./run.sh /path/to/project --experimental  # Enable experimental features (Ollama provider, Sonnet 4.6 + Advisor)
./run-tests.sh                      # All tests (983)
./run-tests.sh tests/smoke/         # Smoke tests only
./run-tests.sh -k "test_cancel"     # Filter by name
```

Server binds to `127.0.0.1:8000` (auto-increments if busy, up to 8019). E2E tests: `./run-e2e-tests.sh`.

**Naming reference**: `AGENT_FILES/PROJECT_MAP.md` defines a shared shorthand vocabulary (`flow.agent-start`, `flow.merge`, `flow.command-gate`, …) — use these names in conversation; both sides resolve them to the same code paths.
