# Backend Services

**Stack**: FastAPI + aiosqlite. `AgentOrchestrator` (`src/agent/orchestrator.py`) is a thin facade delegating to 5 services in `src/services/`:

- `WorkflowService` (1331 LOC) — agent lifecycle, state transitions (driven by `ItemState` FSM in `src/domain/item_state.py`), merge conflict auto-resolution, dependency auto-start, WIP limit queueing, multi-repo session kwargs
- `DatabaseService` (558 LOC) — all DB operations (parameterized; column whitelists now live in the repositories)
- `NotificationService` — WebSocket broadcasting + tool formatting
- `GitService` — worktree management, merge operations, repo path resolution
- `SessionService` — Claude SDK session lifecycle, commit messages, plugin parsing, Ollama config
