# CLAUDE.md

Standalone scrum board that orchestrates Claude agents working on a **separate target project** (or a workspace of sibling git repos in multi-repo mode). Server code lives here; data directory (`agents-lab/`) is created in the target project / workspace root.

## Quick start

```bash
./run.sh /path/to/target-project    # Single-repo mode
./run.sh /path/to/workspace-folder  # Multi-repo mode
./run.sh /path/to/project --experimental  # Ollama provider, Sonnet + Advisor
./run-tests.sh                      # All tests
./run-e2e-tests.sh                  # E2E tests
```

Server binds to `127.0.0.1:8000` (auto-increments up to 8019).

## Docs

Before doing real work, scan **[`AGENT_FILES/CARDS/README.md`](AGENT_FILES/CARDS/README.md)** — the routing manifest — and load only the cards whose **Load when** matches the task. Don't bulk-load.

`AGENT_FILES/` root holds historical snapshots only (`AUDIT.md`, `ASSESSMENT_CODE.md`); living docs are all under `CARDS/`.
