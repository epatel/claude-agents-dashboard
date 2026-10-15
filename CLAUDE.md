# CLAUDE.md

Standalone scrum board that orchestrates Claude agents working on a **separate target project** (or a workspace of sibling git repos in multi-repo mode). Server code lives here; data directory (`agents-lab/`) is created in the target project / workspace root.

## Quick start

```bash
./run.sh /path/to/target-project    # Single-repo mode
./run.sh /path/to/workspace-folder  # Multi-repo mode
./run.sh /path/to/project --experimental  # Experimental features (Ollama + Kimi providers)
./run.sh /path/to/project --ui-map        # PROJECT_MAP overlays (Cmd+Shift+M)
./run-tests.sh                      # All tests (unit/integration/smoke — count in CARDS/TESTING.md)
./run-tests.sh tests/unit/test_x.py -k name  # One file / dir / test (any path narrows the run)
./run-e2e-tests.sh                  # E2E tests (Node Playwright, spawns agents)
```

Server binds to `127.0.0.1:8000` (auto-increments up to 8019).

## Shared plan

@project-plan.md

Always read the shared plan above before starting — it holds the shared goal and current state across agents. When spawning subagents or worktree agents, tell them to read it first and to update its **Current state** and **Decisions** sections before finishing.

## Docs

Before doing real work, scan **[`AGENT_FILES/CARDS/README.md`](AGENT_FILES/CARDS/README.md)** — the routing manifest — and load only the cards whose **Load when** matches the task. Don't bulk-load.

Project skills live in `.claude/skills/` (committed): `review-agentic-setup` and `files-skill` for maintaining this setup, `ste-writing` for doc prose.

`AGENT_FILES/` root holds historical snapshots only (`AUDIT.md`, `ASSESSMENT_CODE.md`, dated `PLAN_*`/`EVAL_*` records) — don't edit those to match current state. Living docs are under `CARDS/`, plus [`docs/item-states.md`](docs/item-states.md) (the `ItemState` FSM and its diagram, kept in sync with `src/domain/item_state.py`).
