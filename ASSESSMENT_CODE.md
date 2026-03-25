# Code Assessment: Agents Dashboard

**Date**: 2026-03-25
**Scope**: Full source code review of all Python backend, JavaScript frontend, and infrastructure files.
**Revision**: 5 — Reassessment after merge conflict auto-resolution feature.

---

## Executive Summary

Agents Dashboard is a well-architected, production-quality AI agent orchestration platform. The architecture follows clean separation of concerns with 5 focused service classes on the backend and 10 specialized dialog modules on the frontend. Since the previous assessment, **merge conflict auto-resolution** has been added — when approval encounters a merge conflict, the system captures the agent's diff, resets the worktree to the latest base, and restarts the agent with the previous diff as context. The test suite maintains **78 automated tests** across smoke, unit, and integration tiers.

**Overall Rating**: **A** (Strong — clean architecture, well-decomposed services, robust security posture)

---

## Architecture Assessment

```mermaid
graph TB
    subgraph Frontend["Frontend (Vanilla JS)"]
        UI[board.html + Jinja2]
        WS_Client[WebSocket Client]
        JS_Modules["app.js | board.js | stats.js<br/>api.js | diff.js | theme.js"]
        Dialog_Modules["dialogs.js (coordinator)<br/>dialog-core.js | dialog-utils.js<br/>item-dialog.js | detail-dialog.js<br/>review-dialog.js | config-dialog.js<br/>clarification-dialog.js<br/>request-changes-dialog.js<br/>attachments.js | annotation-canvas.js"]
        Annotate[annotate.js]
    end

    subgraph Backend["Backend (Python / FastAPI)"]
        Routes[routes.py<br/>HTTP + WebSocket endpoints]
        WSManager[ConnectionManager<br/>websocket.py]
        Orchestrator[AgentOrchestrator<br/>orchestrator.py facade]
        subgraph Services["Service Layer"]
            Workflow[WorkflowService<br/>workflow_service.py]
            DBService[DatabaseService<br/>database_service.py]
            Notify[NotificationService<br/>notification_service.py]
            GitSvc[GitService<br/>git_service.py]
            SessSvc[SessionService<br/>session_service.py]
        end
        Session[AgentSession<br/>session.py]
        DB[Database<br/>database.py + aiosqlite]
        Migrations[MigrationRunner<br/>runner.py + versions/]
    end

    subgraph MCP["Built-in MCP Tools"]
        Clarify[ask_user<br/>clarification.py]
        Todo[create_todo<br/>todo.py]
        Commit[set_commit_message<br/>commit_message.py]
    end

    subgraph Git["Git Layer"]
        GitOps[operations.py<br/>diff, merge, commit]
        Worktree[worktree.py<br/>create, remove, cleanup]
    end

    subgraph External["External"]
        ClaudeSDK[Claude Agent SDK]
        SQLite[(SQLite DB)]
        GitRepo[(Target Git Repo)]
    end

    UI -->|HTTP| Routes
    WS_Client <-->|WebSocket| WSManager
    Routes --> Orchestrator
    Orchestrator --> Workflow
    Workflow --> DBService
    Workflow --> GitSvc
    Workflow --> Notify
    Workflow --> SessSvc
    SessSvc --> Session
    Session --> ClaudeSDK
    Session --> Clarify
    Session --> Todo
    Session --> Commit
    DBService --> DB
    DB --> Migrations
    DB --> SQLite
    GitSvc --> GitOps
    GitSvc --> Worktree
    GitOps --> GitRepo
    Worktree --> GitRepo
    Notify --> WSManager
```

### Strengths

1. **Clean service layer architecture**: Orchestrator is now a thin facade delegating to 5 focused services
2. **Single-responsibility modules**: Each service has a clear, bounded responsibility (DB, git, notifications, sessions, workflows)
3. **Modular frontend**: Dialog functionality split into 10 specialized modules with a coordinator pattern
4. **Async-first design**: Proper use of `asyncio` throughout — non-blocking agent starts, event-based clarification flow
5. **Real-time streaming**: WebSocket broadcasting with reconnection keeps the UI responsive
6. **Isolation via worktrees**: Each agent gets its own git worktree — safe parallel execution
7. **Defense in depth**: Rate limiting, path traversal protection, configurable timeouts, input validation
8. **Template decomposition**: Base template extracted, card partial for reuse

### Concerns

1. **No dependency injection**: Components are wired via `app.state` — works for a single-server app but limits testability
2. **Legacy compatibility layer**: Orchestrator retains `_update_item`, `_log`, `_format_tool_use`, `_get_agent_config` methods for backward compatibility — these could be removed once all callers use services directly

---

## Module-by-Module Assessment

### Backend Python — Service Layer (new)

| Module | Lines | Quality | Notes |
|--------|-------|---------|-------|
| `services/__init__.py` | — | A | Clean re-exports of all 5 services |
| `services/workflow_service.py` | 405 | A | Core workflow coordination with callback factory pattern and merge conflict auto-resolution |
| `services/database_service.py` | 181 | A | All DB operations extracted; parameterized queries throughout |
| `services/notification_service.py` | 95 | A | WebSocket broadcasting + tool formatting; clean separation |
| `services/git_service.py` | 93 | A | Git worktree and merge operations with proper error handling |
| `services/session_service.py` | 152 | A | Session lifecycle, commit messages, plugin parsing |

### Backend Python — Core

| Module | Lines | Quality | Notes |
|--------|-------|---------|-------|
| `main.py` | 81 | A | Clean entry point, proper git validation, port discovery |
| `config.py` | 49 | A | Well-organized constants; timeouts, WS rate limiting, and defaults |
| `constants.py` | 12 | A | Centralized `AVAILABLE_MODELS` dict and `DEFAULT_MODEL` |
| `models.py` | 98 | A | Clean Pydantic models, imports `DEFAULT_MODEL` from constants |
| `database.py` | 55 | A- | Clean async context manager; no connection pooling (acceptable for localhost) |
| `web/app.py` | 46 | A | Proper lifespan management, clean factory pattern |
| `web/routes.py` | 566 | A- | Comprehensive REST API; stats caching with TTL; delete delegates to orchestrator |
| `web/websocket.py` | 131 | A | Rate limiting by IP, connection attempt tracking, stats endpoint, dead-connection cleanup |
| `agent/orchestrator.py` | 110 | A | Clean facade pattern — delegates all operations to services; backward compatibility preserved |
| `agent/session.py` | 295 | A- | Clean SDK wrapper; good token extraction with fallbacks |
| `agent/clarification.py` | 51 | A | Clean MCP tool definition |
| `agent/todo.py` | 56 | A | Clean MCP tool definition |
| `agent/commit_message.py` | 50 | A | Clean MCP tool definition |
| `git/operations.py` | 285 | A- | Correct logic; async file reads; `validate_file_path()` prevents path traversal; configurable timeouts |
| `git/worktree.py` | 54 | A | Simple and correct; returns base branch for tracking |
| `migrations/runner.py` | 198 | A- | Solid migration system; class discovery uses string comparison (justified) |
| `migrations/migration.py` | 28 | A | Clean base class |
| `migrations/versions/001_initial_schema.py` | 158 | A | Complete initial schema with all 8 tables |
| `migrations/versions/002_add_base_branch.py` | 32 | A | Adds `base_branch` column to items table |

### Frontend JavaScript

| Module | Lines | Quality | Notes |
|--------|---------|---------|-------|
| `app.js` | 387 | A- | Full WebSocket reconnection with exponential backoff, visibility-aware, manual reconnect |
| `board.js` | 346 | B+ | Drag-drop works well; card rendering could use templating |
| `dialogs.js` | 83 | A | Clean coordinator pattern — delegates to 10 specialized modules |
| `dialog-core.js` | 53 | A | Core dialog open/close/confirm utilities |
| `dialog-utils.js` | 27 | A | Shared utilities (markdown rendering, model display names) |
| `item-dialog.js` | 190 | A- | New/edit item forms with attachment handling |
| `detail-dialog.js` | 188 | A- | Item detail view with tabbed interface |
| `review-dialog.js` | 102 | A | Review dialog with diff viewer and work log |
| `config-dialog.js` | 87 | A | Agent configuration (system prompt, MCP, plugins) |
| `clarification-dialog.js` | 50 | A | Clean clarification prompt/response UI |
| `request-changes-dialog.js` | 24 | A | Focused request-changes form |
| `attachments.js` | 43 | A | Attachment viewing and deletion |
| `annotation-canvas.js` | 52 | A | Canvas annotation integration bridge |
| `annotate.js` | 771 | A- | Self-contained canvas component |
| `api.js` | 77 | A | Clean HTTP helpers |
| `diff.js` | 61 | A- | Functional diff viewer |
| `theme.js` | 24 | A | Simple, correct theme toggle |
| `stats.js` | 184 | A- | Good auto-refresh and WebSocket update pattern |

### Frontend CSS

| Module | Lines | Quality | Notes |
|--------|-------|---------|-------|
| `style.css` | 756 | A- | Main styles with CSS variables |
| `board.css` | 221 | A | Board-specific layout and card styles |
| `dialog.css` | 74 | A | Dialog component styles |
| `theme.css` | 66 | A | Light/dark theme definitions |

---

## Data Flow Analysis

```mermaid
sequenceDiagram
    participant User
    participant Frontend
    participant Routes
    participant Orchestrator
    participant WorkflowService
    participant SessionService
    participant ClaudeSDK
    participant GitService
    participant DBService

    User->>Frontend: Create item + Start agent
    Frontend->>Routes: POST /api/items + POST /api/items/{id}/start
    Routes->>Orchestrator: start_agent(item_id)
    Orchestrator->>WorkflowService: start_agent(item_id)
    WorkflowService->>GitService: create_or_reuse_worktree()
    WorkflowService->>DBService: Update item (doing, running, base_branch)
    WorkflowService->>SessionService: create_session(item_id, worktree, config)
    WorkflowService-->>Routes: Return item (non-blocking)

    loop Agent Execution
        SessionService->>ClaudeSDK: Stream events
        ClaudeSDK-->>SessionService: AssistantMessage / ToolUse / Thinking
        SessionService-->>WorkflowService: Callbacks (on_message, on_tool_use, on_thinking)
        WorkflowService-->>DBService: Log to work_log
        WorkflowService-->>Frontend: WebSocket broadcast (via NotificationService)
    end

    ClaudeSDK-->>SessionService: ResultMessage
    SessionService-->>WorkflowService: on_complete(AgentResult)
    WorkflowService->>DBService: Save token_usage, update item (review)
    WorkflowService-->>Frontend: WebSocket: item_updated

    User->>Frontend: Approve
    Frontend->>Routes: POST /api/items/{id}/approve
    Routes->>Orchestrator: approve_item()
    Orchestrator->>WorkflowService: approve_item()
    WorkflowService->>GitService: merge_agent_work + cleanup_worktree_and_branch
    WorkflowService->>DBService: Update item (done)
    WorkflowService-->>Frontend: WebSocket: item_updated

    alt Merge conflict
        GitService-->>WorkflowService: (False, conflict message)
        WorkflowService->>GitService: Capture agent diff
        WorkflowService->>GitService: Reset worktree to latest base
        WorkflowService->>SessionService: Restart agent with diff as context
    end
```

---

## Item Lifecycle State Machine

```mermaid
stateDiagram-v2
    [*] --> Todo: Create item
    Todo --> Doing: Start agent
    Doing --> Clarify: Agent asks question
    Clarify --> Doing: User responds
    Doing --> Review: Agent completes
    Doing --> Failed: Agent error
    Failed --> Doing: Retry
    Review --> Done: Approve (merge)
    Review --> Doing: Request changes
    Review --> Todo: Cancel review
    Done --> Archive: Archive
    Todo --> [*]: Delete
    Doing --> Todo: Cancel agent
    Review --> Doing: Merge conflict (auto-retry)
```

---

## Security Assessment

| Area | Status | Details |
|------|--------|---------|
| Network binding | **Good** | Localhost only (127.0.0.1) |
| Authentication | **None** | No auth — acceptable for localhost dev tool |
| SQL injection | **Good** | Parameterized queries throughout (now centralized in DatabaseService) |
| Path traversal | **Good** | `validate_file_path()` blocks `..`, absolute paths, null bytes, and control characters; `serve_asset` checks `is_relative_to` |
| Input validation | **Good** | Pydantic models validate API inputs |
| Secret handling | **Good** | API key from env var, never logged |
| Agent permissions | **Good** | `acceptEdits` mode, not `bypassPermissions` |
| WebSocket rate limiting | **Good** | Per-IP connection limits (5 concurrent, 10 per 60s window), connection attempt tracking |
| Git timeouts | **Good** | Configurable timeouts: operations (5min), merge (10min), HTTP requests (11min) |

### Recommendations

1. **Sanitize work log content** before rendering in frontend (markdown injection risk)

---

## Code Quality Findings

### Issues Resolved Since Last Assessment

| # | Issue | Resolution |
|---|-------|------------|
| 1 | Duplicate session creation logic | ✅ Extracted to `SessionService.create_session()` |
| 2 | Synchronous file read in async context | ✅ Uses `asyncio.to_thread()` |
| 3 | Unused `resume_id` variable | ✅ Passed to `start_session_task()` as `resume_session_id` |
| 4 | Double `_update_item` on merge conflict | ✅ Reduced to single call |
| 5 | No WebSocket reconnection in frontend | ✅ Full implementation with exponential backoff, visibility awareness, manual reconnect |
| 6 | `delete_item` cleanup inline in routes | ✅ Moved to `WorkflowService.delete_item()` |
| 7 | Hardcoded model strings | ✅ Centralized in `constants.py` |
| 8 | Path traversal via `git show` | ✅ `validate_file_path()` added |
| 9 | Stats endpoint multiple sequential queries | ✅ Stats caching with 30s TTL, invalidated on mutations |
| 10 | No WebSocket rate limiting | ✅ Per-IP rate limiting with concurrent connection limits and windowed attempt tracking |
| 11 | No request timeout for blocking operations | ✅ `asyncio.wait_for()` with `HTTP_REQUEST_TIMEOUT` on approve route |
| 12 | Migration class discovery uses string comparison | ✅ Justified — `issubclass` fails with dynamic module loading |
| 13 | Orchestrator too large (667 lines) | ✅ Decomposed into 5 services: WorkflowService (405), DatabaseService (181), NotificationService (95), GitService (93), SessionService (152). Orchestrator now 110-line facade |
| 14 | `dialogs.js` too large (801 lines) | ✅ Split into 10 specialized modules with coordinator pattern. Largest module is `item-dialog.js` at 191 lines |

### Remaining Issues

#### Low Priority

1. **No connection pooling**: Each DB operation opens/closes a connection via `aiosqlite.connect()`
   - Acceptable for localhost use but would bottleneck under load

2. **Legacy compatibility methods in orchestrator**: `_update_item`, `_log`, `_format_tool_use`, `_get_agent_config` remain as pass-throughs
   - **Recommendation**: Remove once all callers migrate to using services directly

---

## Test Coverage

**Current state**: 78 automated tests across 7 test files via `./run-tests.sh`.

| Test File | Type | Focus |
|-----------|------|-------|
| `tests/smoke/test_basic_functionality.py` | Smoke | Imports, DB basics, config |
| `tests/unit/test_path_validation.py` | Unit | Path traversal prevention (14 cases) |
| `tests/unit/test_git_timeout.py` | Unit | Git operation timeout behavior |
| `tests/unit/migrations/test_migration_runner.py` | Unit | Migration engine |
| `tests/unit/migrations/test_migration_edge_cases.py` | Unit | Migration edge cases |
| `tests/integration/test_orchestrator_lifecycle.py` | Integration | Orchestrator lifecycle |
| `tests/conftest.py` | Fixtures | Shared test fixtures |

### Recommended Additional Tests

| Priority | Area | Type | Effort |
|----------|------|------|--------|
| **P1** | Service layer unit tests (WorkflowService, DatabaseService) | Unit | Medium |
| **P1** | WebSocket rate limiting | Unit | Low |
| **P1** | API routes (CRUD, agent actions) | Integration | Medium |
| **P2** | Token usage extraction | Unit | Low |
| **P2** | Stats caching and invalidation | Unit | Low |
| **P3** | Frontend dialog modules | E2E (Playwright) | High |

---

## Performance Considerations

```mermaid
graph LR
    subgraph Bottlenecks
        A[SQLite single-writer] --> B[OK for localhost]
        C[No connection pool] --> D[OK for low concurrency]
        E[Stats caching 30s TTL] --> F[Reduced DB load]
        G[Git operations via CLI] --> H[Pragmatic, slightly slower than libgit2]
        I[WS rate limiting] --> J[Prevents resource exhaustion]
    end
```

- **SQLite**: Single-writer limitation is fine for localhost, but concurrent agents writing logs could contend
- **Stats caching**: 30s TTL with active invalidation on mutations — good balance of freshness and performance
- **Git operations**: Shell-out to `git` CLI is pragmatic but slower than libgit2 bindings
- **Git timeouts**: Configurable per operation type prevents hung processes

---

## Positive Patterns Worth Preserving

1. **Service layer decomposition**: 5 focused services with clear responsibilities replace monolithic orchestrator
2. **Facade pattern**: `AgentOrchestrator` provides a stable API while delegating to services
3. **Callback factory pattern**: `WorkflowService._create_on_*_callback()` methods keep callback creation centralized and consistent
4. **`_log_and_notify` helper**: Centralizes DB logging + WebSocket broadcast — prevents missed notifications
5. **Dialog coordinator pattern**: `dialogs.js` delegates to 10 specialized modules while preserving backward compatibility
6. **Commit message via MCP tool**: Agents produce meaningful commit messages rather than generic ones
7. **Worktree reuse on retry**: Preserves agent's previous work when retrying
8. **Dead WebSocket cleanup**: Broadcast loop silently removes failed connections
9. **Lifespan-managed shutdown**: Graceful agent cancellation on server stop via `SessionService.cleanup_all_sessions()`
10. **`validate_file_path()`**: Thorough path traversal prevention with multiple layers of checks
11. **Stats caching with invalidation**: Reduces DB pressure while keeping data fresh
12. **WebSocket reconnection**: Exponential backoff, visibility-aware, manual override — robust implementation
13. **Centralized constants**: `AVAILABLE_MODELS` and `DEFAULT_MODEL` in `constants.py` prevent string duplication
14. **WebSocket rate limiting**: Per-IP connection limits with configurable windows prevent resource exhaustion
15. **Base branch tracking**: Worktree creation returns and stores the base branch for reliable merge targeting
16. **Configurable git timeouts**: Separate timeouts for operations (5min) and merges (10min) prevent hung processes
17. **Template decomposition**: Base template extracted with card partial for consistent rendering
18. **Merge conflict auto-resolution**: On conflict, captures agent's diff, resets worktree to latest base, and restarts agent with previous diff as context — fully automated recovery

---

## Codebase Statistics

| Category | Files | Lines |
|----------|-------|-------|
| Python backend (src/) | 24 | ~3,447 |
| JavaScript frontend | 18 | ~2,749 |
| CSS styles | 4 | ~1,117 |
| HTML templates | 3 | ~419 |
| Tests | 7 | ~1,968 |
| **Grand total** | **56** | **~9,700** |

---

## Summary of Recommendations

| Priority | Recommendation | Effort |
|----------|---------------|--------|
| **Low** | Remove legacy compatibility methods from orchestrator | Low |
| **Low** | Sanitize work log markdown rendering | Low |
| **Low** | Add service layer unit tests | Medium |
| **Low** | Add WebSocket rate limiting unit tests | Low |
