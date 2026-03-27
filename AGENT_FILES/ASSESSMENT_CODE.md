# Code Assessment: Agents Dashboard

**Date**: 2026-03-27
**Scope**: Full source code review of all Python backend, JavaScript frontend, and infrastructure files.
**Revision**: 10 — Maintenance reassessment with updated test counts (139), line counts, codebase statistics, and new agent tools (board_view, tool_access, tool_filter).

---

## Executive Summary

Agents Dashboard is a well-architected, production-quality AI agent orchestration platform. The architecture follows clean separation of concerns with 5 focused service classes on the backend and 10 specialized dialog modules on the frontend. Since the previous assessment, a **file browser** has been added, along with **allowed commands** with runtime approval, **bash YOLO mode**, **base commit pinning** for stable diffs, **board introspection** (view_board MCP tool), **tool access requests** (request_tool_access MCP tool), and **tool filtering** (PreToolUse hook for optional built-in tools). The test suite includes **139 automated tests** across smoke, unit, and integration tiers plus **E2E tests** via `run-e2e-tests.sh`, with coverage for diff isolation, command filtering, file browser routes, mini-MCP server protocol, and orchestrator lifecycle.

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
        FileBrowser[file-browser.js]
    end

    subgraph Backend["Backend (Python / FastAPI)"]
        Routes[routes.py<br/>HTTP + WebSocket endpoints]
        FileRoutes[file_routes.py<br/>File browser API]
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
        CmdAccess[request_command_access<br/>command_access.py]
        BoardView[view_board<br/>board_view.py]
        ToolAccess[request_tool_access<br/>tool_access.py]
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
| `services/workflow_service.py` | 656 | A | Core workflow coordination with callback factory pattern and merge conflict auto-resolution |
| `services/database_service.py` | 226 | A | All DB operations extracted; parameterized queries throughout |
| `services/notification_service.py` | 95 | A | WebSocket broadcasting + tool formatting; clean separation |
| `services/git_service.py` | 94 | A | Git worktree and merge operations with proper error handling |
| `services/session_service.py` | 177 | A | Session lifecycle, commit messages, plugin parsing |

### Backend Python — Core

| Module | Lines | Quality | Notes |
|--------|-------|---------|-------|
| `main.py` | 89 | A | Clean entry point, proper git validation, port discovery |
| `config.py` | 109 | A | Well-organized constants; timeouts, WS rate limiting, defaults, and file browser configuration |
| `constants.py` | 12 | A | Centralized `AVAILABLE_MODELS` dict and `DEFAULT_MODEL` |
| `models.py` | 100 | A | Clean Pydantic models, imports `DEFAULT_MODEL` from constants |
| `database.py` | 55 | A- | Clean async context manager; no connection pooling (acceptable for localhost) |
| `web/app.py` | 49 | A | Proper lifespan management, clean factory pattern |
| `web/routes.py` | 586 | A- | Comprehensive REST API; stats caching with TTL; delete delegates to orchestrator |
| `web/file_routes.py` | 199 | A | File browser endpoints with path validation, secret hiding, binary detection, language mapping, lazy tree scanning |
| `web/websocket.py` | 131 | A | Rate limiting by IP, connection attempt tracking, stats endpoint, dead-connection cleanup |
| `agent/orchestrator.py` | 110 | A | Clean facade pattern — delegates all operations to services; backward compatibility preserved |
| `agent/session.py` | 398 | A- | Clean SDK wrapper; good token extraction with fallbacks |
| `agent/clarification.py` | 51 | A | Clean MCP tool definition |
| `agent/todo.py` | 94 | A | Clean MCP tool definition |
| `agent/commit_message.py` | 50 | A | Clean MCP tool definition |
| `agent/command_access.py` | 42 | A | Clean MCP tool for runtime command approval |
| `agent/command_filter.py` | 42 | A | PreToolUse hook for bash command filtering |
| `agent/board_view.py` | 42 | A | Board introspection MCP tool |
| `agent/tool_access.py` | 42 | A | Runtime tool access request MCP tool |
| `agent/tool_filter.py` | 38 | A | PreToolUse hook for optional built-in tool filtering |
| `git/operations.py` | 313 | A- | Correct logic; async file reads; `validate_file_path()` prevents path traversal; configurable timeouts |
| `git/worktree.py` | 73 | A | Simple and correct; returns base branch for tracking |
| `migrations/runner.py` | 198 | A- | Solid migration system; class discovery uses string comparison (justified) |
| `migrations/migration.py` | 28 | A | Clean base class |
| `migrations/versions/001_initial_schema.py` | 158 | A | Complete initial schema with all 8 tables |
| `migrations/versions/002_add_base_branch.py` | 32 | A | Adds `base_branch` column to items table |
| `migrations/versions/003_add_allowed_commands.py` | 36 | A | Adds `allowed_commands` to agent_config |
| `migrations/versions/004_add_bash_yolo.py` | 27 | A | Adds `bash_yolo` flag to agent_config |
| `migrations/versions/005_add_base_commit.py` | 32 | A | Adds `base_commit` SHA to items table |
| `migrations/versions/006_add_allowed_builtin_tools.py` | 31 | A | Adds `allowed_builtin_tools` JSON array to agent_config |

### Frontend JavaScript

| Module | Lines | Quality | Notes |
|--------|---------|---------|-------|
| `app.js` | 392 | A- | Full WebSocket reconnection with exponential backoff, visibility-aware, manual reconnect |
| `board.js` | 346 | B+ | Drag-drop works well; card rendering could use templating |
| `dialogs.js` | 83 | A | Clean coordinator pattern — delegates to 10 specialized modules |
| `dialog-core.js` | 53 | A | Core dialog open/close/confirm utilities |
| `dialog-utils.js` | 27 | A | Shared utilities (markdown rendering, model display names) |
| `item-dialog.js` | 190 | A- | New/edit item forms with attachment handling |
| `detail-dialog.js` | 188 | A- | Item detail view with tabbed interface |
| `review-dialog.js` | 102 | A | Review dialog with diff viewer and work log |
| `config-dialog.js` | 144 | A | Agent configuration (system prompt, MCP, plugins) |
| `clarification-dialog.js` | 117 | A | Clean clarification prompt/response UI |
| `request-changes-dialog.js` | 24 | A | Focused request-changes form |
| `attachments.js` | 43 | A | Attachment viewing and deletion |
| `annotation-canvas.js` | 52 | A | Canvas annotation integration bridge |
| `annotate.js` | 936 | A- | Self-contained canvas component |
| `file-browser.js` | 630 | A | Full-featured file browser with tree view, tabbed viewer, lazy loading, keyboard navigation, filter, breadcrumbs, markdown/mermaid rendering |
| `api.js` | 77 | A | Clean HTTP helpers |
| `diff.js` | 61 | A- | Functional diff viewer |
| `theme.js` | 24 | A | Simple, correct theme toggle |
| `stats.js` | 184 | A- | Good auto-refresh and WebSocket update pattern |

### Frontend CSS

| Module | Lines | Quality | Notes |
|--------|-------|---------|-------|
| `style.css` | 775 | A- | Main styles with CSS variables |
| `board.css` | 221 | A | Board-specific layout and card styles |
| `dialog.css` | 74 | A | Dialog component styles |
| `file-browser.css` | 557 | A | File browser layout, tree, tabs, viewer, code/markdown/image styles, Prism.js light theme overrides, responsive |
| `theme.css` | 66 | A | Light/dark theme definitions |

**Note**: CSS total is ~1,629 lines across 5 modules.

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
| Path traversal | **Good** | `validate_file_path()` blocks `..`, absolute paths, null bytes, and control characters; `serve_asset` checks `is_relative_to`; `validate_file_browser_path()` adds symlink-escape detection |
| Input validation | **Good** | Pydantic models validate API inputs |
| Secret handling | **Good** | API key from env var, never logged; file browser hides `.env`, `*.key`, `*.pem`, credentials, and SSH keys |
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
| 13 | Orchestrator too large (667 lines) | ✅ Decomposed into 5 services: WorkflowService (537), DatabaseService (199), NotificationService (95), GitService (94), SessionService (163). Orchestrator now 110-line facade |
| 14 | `dialogs.js` too large (801 lines) | ✅ Split into 10 specialized modules with coordinator pattern. Largest module is `item-dialog.js` at 190 lines |

### Remaining Issues

#### Low Priority

1. **No connection pooling**: Each DB operation opens/closes a connection via `aiosqlite.connect()`
   - Acceptable for localhost use but would bottleneck under load

2. **Legacy compatibility methods in orchestrator**: `_update_item`, `_log`, `_format_tool_use`, `_get_agent_config` remain as pass-throughs
   - **Recommendation**: Remove once all callers migrate to using services directly

---

## Test Coverage

**Current state**: 139 automated tests across 10 test files via `./run-tests.sh`, plus E2E tests via `./run-e2e-tests.sh`.

| Test File | Type | Tests | Focus |
|-----------|------|-------|-------|
| `tests/smoke/test_basic_functionality.py` | Smoke | 12 | Imports, DB basics, config |
| `tests/unit/test_path_validation.py` | Unit | 14 | Path traversal prevention |
| `tests/unit/test_git_timeout.py` | Unit | 5 | Git operation timeout behavior |
| `tests/unit/test_file_routes.py` | Unit | 35 | File browser path validation, secret detection, language mapping, directory scanning, file content reading |
| `tests/unit/test_allowed_commands.py` | Unit | 14 | Command filter hook, command access MCP tool, permission persistence, YOLO mode |
| `tests/unit/test_diff_mixing.py` | Unit | 6 | Diff isolation between items, concurrent diffs, base commit pinning |
| `tests/unit/test_mini_mcp.py` | Unit | 11 | Mini-MCP server stdio protocol, JSON-RPC messages, tool invocation |
| `tests/unit/migrations/test_migration_runner.py` | Unit | 14 | Migration engine |
| `tests/unit/migrations/test_migration_edge_cases.py` | Unit | 14 | Migration edge cases |
| `tests/integration/test_orchestrator_lifecycle.py` | Integration | 14 | Orchestrator lifecycle |
| `tests/conftest.py` | Fixtures | — | Shared test fixtures |

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
19. **File browser with defense in depth**: Path validation (null bytes, control chars, traversal, symlink escape), secret file hiding via configurable patterns, binary detection, configurable size limits, excluded dirs/files — all constants centralized in `config.py`
20. **Lazy tree loading**: File browser loads directory children on-demand with configurable depth limit, reducing initial payload for large projects

---

## Codebase Statistics

| Category | Files | Lines |
|----------|-------|-------|
| Python backend (src/) | 41 | ~4,604 |
| JavaScript frontend | 19 | ~3,796 |
| CSS styles | 5 | ~1,693 |
| HTML templates | 3 | ~495 |
| Tests | 11 | ~2,892 |
| **Grand total** | **79** | **~13,480** |

---

## Summary of Recommendations

| Priority | Recommendation | Effort |
|----------|---------------|--------|
| **Low** | Remove legacy compatibility methods from orchestrator | Low |
| **Low** | Sanitize work log markdown rendering | Low |
| **Low** | Add service layer unit tests | Medium |
| **Low** | Add WebSocket rate limiting unit tests | Low |
