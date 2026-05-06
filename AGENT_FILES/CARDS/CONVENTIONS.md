# Project Conventions

> **Load when**: writing or reviewing non-trivial code in `src/`.
> **Skip when**: doc-only edits or single-line fixes that don't introduce new patterns.

Code style, naming, and idioms actually used in this codebase. Read this before writing new code so the diff blends in.

This is a Python 3.12+ FastAPI + aiosqlite app with a vanilla-JS frontend (no build step) and a Claude SDK agent runtime. Layers go `domain → repositories → services → web/agent`. Most code is AI-written; favor simple, concrete patterns over abstraction.

## Canonical conventions

### Naming

- **Files**: `snake_case.py` for Python (`workflow_service.py`), `kebab-case.js` for JS (`clarification-dialog.js`, `dialog-core.js`).
- **Classes**: `PascalCase` (`ItemRepository`, `WorkflowService`).
- **Functions / methods**: `snake_case`. Module-private helpers prefixed with `_` (`_count_running_agents`, `_audit_item_state_encodings`). Async methods are unprefixed — `async def start_agent`, not `async_start_agent`.
- **Constants**: `SCREAMING_SNAKE_CASE` (`HEARTBEAT_INTERVAL`, `SHELL_OPERATORS`, `MINIMUM_CLAUDE_CLI_VERSION`).
- **JS namespaces**: one `PascalCase` global object per file, declared at top: `const Board = { ... }`, `const Api = { ... }`. No ES modules, no bundler. Files are pulled in via `<script>` tags from `base.html`.
- **Test files**: `tests/unit/test_<thing>.py` (pytest), `tests/e2e/test_<thing>.mjs` (Node Playwright). Cases grouped under `class TestThing:` (e.g. `TestColumnEncoding`, `TestGetOrRaise`). Test names are descriptive sentences: `test_doing_with_no_status_falls_back_to_backlog`.
- **Migrations**: `src/migrations/versions/NNN_short_description.py`. Class is `<Name>Migration` (e.g. `AddContextToClarificationsMigration`).

### File organization

- `src/domain/` — pure Python, no framework or DB imports. Today: `item_state.py` (the FSM).
- `src/repositories/` — facades over `DatabaseService`. Returns plain dicts, not Pydantic. Owns column allowlists at this boundary.
- `src/services/` — orchestrate I/O. `WorkflowService` is the big one; the others are focused.
- `src/web/` — FastAPI app (`app.py`), HTTP routes (`routes.py`, `file_routes.py`), WebSocket (`websocket.py`).
- `src/agent/` — Claude SDK integration: one file per built-in MCP tool (`clarification.py`, `todo.py`, …) and one per PreToolUse hook (`command_filter.py`, `tool_filter.py`, `path_guard.py`).
- `src/models.py` — Pydantic models for the HTTP boundary.
- `src/constants.py`, `src/config.py` — configuration and constants.
- `src/static/js/` — flat (no subfolders for dialogs). `src/templates/{base,board}.html` + `src/templates/partials/`.
- Tests: `tests/{unit,unit/migrations,integration,smoke,e2e}/`.

### Module boundaries

- **Imports inside `src/`**: relative (`from ..domain.item_state import ...`).
- **Imports inside `tests/`**: absolute (`from src.database import Database`).
- **Domain imports nothing from the framework or DB layer.** It's pure stdlib.
- **Layer direction**: `domain ← repositories ← services ← web / agent`. Don't reverse it.
- **Cycle breaks**: when a repository needs `DatabaseService` only for typing, gate the import behind `if TYPE_CHECKING:` and add `from __future__ import annotations`. See `src/repositories/item_repository.py:21` for the pattern, comment included.

### Type hints

New code uses modern style. Migrate older files when you touch them.

- `X | None`, **not** `Optional[X]`.
- `dict[K, V]` / `list[X]` / `tuple[...]`, **not** `Dict` / `List` / `Tuple` from `typing`.
- Add `from __future__ import annotations` at the top of new modules.
- `Any` is fine where it reflects reality (repos return `dict[str, Any]` for items).
- Pydantic only at the HTTP boundary (`src/models.py`). Repositories return plain dicts. See the `AgentConfig` docstring in `models.py` for the "tolerate raw JSON on input" pattern when a Pydantic field is loaded from a SQLite `TEXT` column.

### Error handling

The codebase has three error shapes, used at three layers — this is deliberate, not contradictory:

- **Domain & repositories**: raise typed exceptions. `ItemNotFound` from `repo.get_or_raise`, `InvalidTransition` and `UnknownStateEncoding` from `domain/item_state.py`. Be honest about absence.
- **Services**: methods that can be called from MCP callbacks return `dict[str, Any]` like `{"success": True, ...}` or `{"success": False, "error": "..."}`. Don't raise across that boundary — MCP tool responses must serialize to JSON. Internal helpers can still raise.
- **HTTP routes**: `raise HTTPException(status_code=..., detail="...")`. Translate domain exceptions into HTTP at this layer.
- **PreToolUse hooks**: return a structured deny dict, never raise. See `src/agent/command_filter.py:hook` — `{"hookSpecificOutput": {"permissionDecision": "deny", "permissionDecisionReason": "..."}}`.
- **Startup audits**: log a warning with sample rows and continue. Production data may include encodings from older code paths; don't crash on them. See `_audit_item_state_encodings` in `web/app.py`.

### State machine

Workflow state changes go through `ItemState.transition(state, event)` in `src/domain/item_state.py`, or — for repository writes — through `ItemRepository.transition(item_id, event)`. Raw `column_name` / `status` writes outside the SM are a regression. The one intentional exception is the drag-and-drop `move_item` route, which produces canonical encodings via the repo without going through `transition()` (the user is overriding the SM, not following a workflow event).

### Async / concurrency

- `async def` everywhere in `src/services/`, `src/web/`, `src/repositories/`. aiosqlite for the DB.
- Background work via `asyncio.create_task(...)` — never threads.
- Cross-task signaling via `asyncio.Event` (see `_clarify_events` in `WorkflowService`).
- Periodic tasks: kick off from `lifespan` in `web/app.py`, sleep loop inside.

### Data layer

- aiosqlite, raw SQL (no ORM). All writes parameterized with `?`.
- `items` and `epics` writes go through their repository facade (column allowlist `_WRITABLE_ITEM_COLUMNS` lives at the repo boundary).
- Other tables (`clarifications`, `reviews`, `work_log`, `attachments`, `tokens`, `item_dependencies`, agent config) still go through `DatabaseService` directly. **Policy**: tables graduate to a dedicated repo only when a third writer shows up or a typing pain point makes the boundary obvious. Don't pre-emptively add repos.
- Migrations are numbered (`NNN_*`), implement `up()` and `down()`. For column-add migrations, leaving `down()` as a no-op is acceptable — match the comment style in `021_add_context_to_clarifications.py`.

### Logging

- `import logging` at module top, `logger = logging.getLogger(__name__)` immediately after imports. ~19 modules follow this exactly.
- `logger.warning(...)` for recoverable problems, `logger.info(...)` for state transitions, `logger.error(...)` for caught exceptions you don't re-raise. Don't reach for `print()`.

### Frontend

- One namespace per file: `const ReviewFileBrowser = { ... }`. No imports, no exports.
- API calls go through the `Api` namespace (`Api.getItems()`, `Api.request(method, url, body)`). Don't `fetch()` directly from a dialog or board module.
- Dialogs go through `Dialogs.confirm/prompt/...` — never browser `confirm()` / `prompt()` (they block the event loop and don't theme).
- WebSocket events fan out from `app.js`.
- The Jinja2 `templates/partials/card.html` and the JS `Board.renderCard` builder both render cards. They must stay in sync — when you add a card field, edit both. The repo-color hash (`_repo_hue` in `app.py` ↔ `Board.repoHue` in `board.js`) is a deliberate parallel implementation; preserve the algorithm.

### Testing

- pytest + `pytest_asyncio`. Fixtures via `@pytest_asyncio.fixture`. Shared fixtures in `tests/conftest.py`.
- Mocks use `unittest.mock.AsyncMock` / `MagicMock`. Spec mocks against the real class (`MagicMock(spec=ConnectionManager)`).
- Group cases under `class Test<Concern>:`. Each test does one thing; name describes the scenario.
- E2E tests live in `tests/e2e/*.mjs` and cost real Claude tokens — they're driven by `run-e2e-tests.sh` against a separate harness directory (`claude-agents-dashboard-e2e-test/`), never the main repo.

### Comments and docstrings

- Module docstring on every non-trivial file, explaining the file's role in one short paragraph.
- Class docstring: one line.
- Inline comments lean toward "why," not "what." If a piece of code references a refactor decision (e.g. "moved here as part of Phase 2.5"), keep that reference — it explains the shape.
- Cite specific migrations when documenting a non-obvious choice.

### Security / hardening

- PreToolUse hooks are defense-in-depth. Allowlist match happens **after** rejecting commands containing shell operators (`;`, `&&`, `||`, `|`, `>`, `>>`, `<`, `$(`, `` ` ``). See `src/agent/command_filter.py:_contains_shell_operators`.
- CORS is restricted to `127.0.0.1` and `localhost` across the app's port range only. Don't widen it.
- `path_guard.py` prevents agents from editing files outside their worktree. New file-touching tools must be on its known list or they get denied.

### Simplicity bias

This codebase is largely AI-agent-authored, and that puts a premium on staying simple:

- Don't introduce a class hierarchy, generic, or abstraction unless there are at least two concrete callers that need it.
- Don't add a config knob "for flexibility" — wait for the second use case.
- Don't write defensive code for impossible states. If `transition()` already enforces an invariant, downstream code should trust it.
- Three similar lines beats a premature helper.

## Legacy patterns — recognize, do not extend

You will see these in older files. Don't produce more.

- **`Optional[X]` / `Dict[K,V]` / `List[X]` from `typing`** — replaced by `X | None` and lowercase builtins. If you're already editing the file, migrate the signatures you touch; a whole-file conversion in an unrelated PR is churn.
- **Modules without `from __future__ import annotations`** — add it on first edit if you're introducing forward refs or `if TYPE_CHECKING:` imports.
- **Off-canon `(column_name="doing", status=None)` rows** — the DnD-staged encoding. Read-tolerant via `from_columns`, never produced by `to_columns`. Don't write code that emits this.

## Exemplar files

When in doubt, read these:

- **Domain / state machine**: `src/domain/item_state.py`
- **Repository facade**: `src/repositories/item_repository.py`
- **Focused service**: `src/services/notification_service.py`
- **HTTP route handler**: `src/web/routes.py::board_page` (~`routes.py:181`)
- **MCP tool server**: `src/agent/clarification.py`
- **PreToolUse hook**: `src/agent/command_filter.py`
- **Migration**: `src/migrations/versions/021_add_context_to_clarifications.py`
- **Test (with FSM-style class grouping)**: `tests/unit/test_item_state.py`
- **Frontend namespace module**: `src/static/js/api.js`

## Gaps

The codebase has no clear opinion on these. Ask before establishing one:

- No formatter or linter is configured (no `ruff`, `black`, `flake8`, or `eslint` config files). New formatting decisions should be discussed before adding tooling.
- No structured logging — plain `logger.info(...)` strings only.
- No type-checker (`mypy` / `pyright`) is run in CI; type hints are documentation, not enforcement.

---

_Generated by the files-skill conventions distiller. Re-run after the next refactor phase to surface migration progress._
