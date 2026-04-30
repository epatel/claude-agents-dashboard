# Refactor Plan — toward Abstract Data Types, clean modules, explicit state machines

**Status:** not started
**Goal:** move the codebase from "stringly-typed records + 1.3k-line god module" toward typed state machines and encapsulated repositories, **incrementally**. Every phase is independently shippable; we can stop after any phase and the codebase is still in a coherent state.

**Non-goals:** rewrite, big-bang migration, swapping frameworks, dropping Pydantic, switching DB.

---

## Progress tracker

Tick a box when the task is fully landed (PR merged, tests green). Sub-tasks roll up — a phase is done only when every box under it is ticked.

### Phase 1 — Explicit `Item` state machine (highest leverage, no DB migration)

Today: state is `(column_name: str, status: Optional[str])`, ~10 valid combinations, invariants enforced ad-hoc across `services/workflow_service.py` (1354 LOC).

After: a single `ItemState` enum + a `TRANSITIONS` table. Illegal moves raise. DB columns unchanged.

- [x] **1.1** Create `src/domain/__init__.py` and `src/domain/item_state.py`
  - `class ItemState(StrEnum)` — enumerate every reachable state (BACKLOG, QUEUED, RUNNING, PAUSED, CLARIFY, MERGE_CONFLICT, REVIEW, DONE, CANCELED, …)
  - `class Event(StrEnum)` — START, PAUSE, RESUME, ASK, ANSWER, REQUEST_MERGE, CONFLICT, COMPLETE, CANCEL, REQUEUE
  - `TRANSITIONS: dict[tuple[ItemState, Event], ItemState]`
  - `transition(state, event) -> ItemState` raising `InvalidTransition`
  - Helpers: `from_columns(column_name, status) -> ItemState` and `to_columns(state) -> tuple[str, Optional[str]]`
  - **Landed:** 13 states grounded in audit of `workflow_service.py` writes; smoke-tested roundtrip + illegal-transition raise.
- [x] **1.2** Audit & document current state combos
  - Grep `column_name` and `status` writes in `workflow_service.py`; list every `(col, status)` pair actually written
  - Save the audit in `docs/item-states.md` (one-time artifact — fine to delete after Phase 1 lands)
  - Render `TRANSITIONS` as a Mermaid state diagram in the same doc
  - **Landed:** `docs/item-states.md` with encoding table, Mermaid diagram, and audit table mapping every `workflow_service.py` write to a state.
- [x] **1.3** Unit tests for the state machine
  - Every legal transition has a test
  - Every `(state, event)` not in the table raises
  - `from_columns` ↔ `to_columns` roundtrip for all known DB rows
  - **Landed:** `tests/unit/test_item_state.py` — 53 tests; full suite 936 passed.
- [x] **1.4** Route the **start/pause/resume/cancel** call sites through `transition(...)`
  - These are the most-traveled paths; smallest blast radius for the first migration
  - Keep DB writes as-is (`column_name` / `status` strings)
  - No behavior change — just funnel mutations through the SM
  - **Landed:** migrated `_enqueue_item`, `_start_agent_internal`, `cancel_agent`, `pause_agent`, `resume_agent`. Discovered `(CANCELLED, START)` and `(FAILED, START)` are real production paths and added them. Caught a hidden bug where `pause_agent` could leave items in `(todo, paused)` (impossible state) — now raises `InvalidTransition`. Suite 940 passing.
- [x] **1.5** Route **clarify (ask/answer)** through `transition(...)`
  - **Landed:** 7 call sites migrated — `_create_on_clarify_callback` (ASK + ANSWER), `_create_on_request_command_callback` (ASK + ANSWER on deny), `_create_on_request_tool_callback` (ASK + ANSWER on deny), `_restart_session_with_new_permissions` (ANSWER on approve). Same fixture-shape bug surfaced in `TestOnClarifyCallback` (7 tests called `on_clarify` on a BACKLOG item — meaningless in production, agent only calls it while RUNNING). Suite 940 passing.
- [x] **1.6** Route **merge / merge-conflict / complete** through `transition(...)`
  - **Landed:** 11 call sites in `_create_on_complete_callback`, `_create_on_error_callback`, `request_changes`, `cancel_review`, and `approve_item` (3× REQUEST_MERGE, 1× MERGE_BLOCKED, 2× CONFLICT_DETECTED, 1× RESOLVE_CONFLICTS).
  - Surfaced a Phase 1.1 modeling error: `CONFLICT` is `("review", "conflict")`, not `("doing", "conflict")` — the original audit missed that `update_item(item_id, status="conflict")` (no column_name) inherits the current column, which is `review` during `approve_item`. Conflict detection and resolve-retry both transition from `REVIEW`, not `RUNNING`. Fixed mapping + transitions; CONFLICT is terminal pending manual `REQUEUE`/`CANCEL`.
  - Added `REQUEST_CHANGES` event (REVIEW → RUNNING) for the user-driven feedback loop.
  - Caught a real bug: `_create_on_complete_callback` referenced `current_item` in the failure branch where it was never defined. Fix: fetch in both branches.
  - Suite 944 passing.
- [x] **1.7** Route **WIP-limit queueing / dequeue** through `transition(...)`
  - **Landed:** WIP queue/dequeue itself was already routed in 1.4 (via `_enqueue_item` / `_start_agent_internal`). This phase mopped up the two remaining literal-string sites: `retry_agent` (FAILED → START → RUNNING) and `routes.py:retry_merge` (MERGE_BLOCKED/CONFLICT → RETRY_MERGE → REVIEW).
  - Added `RETRY_MERGE` event with edges from MERGE_BLOCKED and CONFLICT.
  - Pruned the speculative `(MERGE_BLOCKED, ANSWER) → REVIEW` transition introduced in 1.1 — never used in production code (merge-blocked exit is the retry-merge route, not the clarify dialog).
  - Verification: `grep 'update_item.*column_name="\|update_item.*status="'` over the entire codebase returns zero matches. Bulk SQL archive in `routes.py:archive_items_by_date` left as-is (state machine targets `update_item` writes; bulk operations are a Phase 2 repository concern).
  - Suite 946 passing.
- [x] **1.8** Add a startup invariant check: load every item, assert `from_columns(...)` succeeds. Log + skip on bad rows; do not crash.
  - **Landed:** `_audit_item_state_encodings(db)` runs in `lifespan` after `db.initialize()`. Walks every row through `from_columns`, collects unknown encodings, logs a single warning with sample rows. Does not raise. Tested on clean / dirty / empty DBs.
- [x] **1.9** Delete dead code revealed by 1.4–1.7 (defensive checks now redundant)
  - **Landed:** scope was smaller than expected — the migrations routed writes through the SM but didn't orphan many call sites. The substantive cleanup was `find_stale_worktrees`: replaced its `status == "cancelled" or column in ("done", "archive")` string-juggling with a single `state in {CANCELLED, DONE, ARCHIVED}` check, and the `column == "todo" and status not in ("running", "paused")` condition with `state is BACKLOG`. The earlier (MERGE_BLOCKED, ANSWER) speculative transition was already pruned in 1.7.

**Acceptance:** every write to `items.column_name` / `items.status` in production code goes through `transition(...)`. Grep should find no direct assignments outside the state-machine module and migrations.

**Est size:** Phase 1 ≈ 1–2 PRs, ~300–500 LOC net (mostly delete).

---

### Phase 1 followups (discovered post-Phase 1)

- [ ] **DnD endpoint bypass.** The drag-and-drop `move_item` endpoint (`routes.py:506`) updates `column_name` without touching `status`, producing off-canon encodings like `("doing", None)`. Phase 1.10 added a tolerant fallback in `from_columns`, but the right fix is to route DnD writes through the SM too. Fold this into Phase 2 when `ItemRepository.move(...)` is introduced.

### Phase 2 — Repository ADT for items (encapsulation)

Today: `database_service.py` (525 LOC) takes `dict[str, Any]` and uses `ALLOWED_ITEM_COLUMNS` / `ALLOWED_EPIC_COLUMNS` whitelists to filter — symptomatic of leaking column names to callers.

After: callers never see column names. They call intent-named methods. The whitelist disappears.

- [x] **2.1** Create `src/repositories/item_repository.py` with the **read** API first
  - `async def get(id) -> Item`, `list_by_column(col) -> list[Item]`, `list_running() -> list[Item]`, etc.
  - Migrate `workflow_service.py` reads to use it. No write methods yet.
  - **Landed:** `ItemRepository` with `get`, `get_or_raise`, `list_all`, `list_in_state(state)`, `list_running`, `list_queued`. Uses `to_columns()` so callers don't repeat the encoding. Wired into orchestrator + WorkflowService. Migrated 5 read sites: `_start_agent_internal`, `resume_agent`, `retry_agent`, `approve_item` (all to `get_or_raise`), and `process_queue` (to `list_queued`). Saved 8 lines of `if not item: raise ValueError` boilerplate.
  - `ItemNotFound` subclasses `ValueError` for backwards compatibility.
  - Hit a circular import (`repositories.item_repository` ↔ `services.workflow_service`); fixed via `TYPE_CHECKING` for the `DatabaseService` type hint and dropping the package-level re-export. Callers import from `repositories.item_repository` directly.
  - Suite 960 passing.
- [x] **2.2** Add **state-changing** methods on `ItemRepository`
  - `async def transition(id, event) -> Item` — single source of truth for state writes; uses Phase 1 SM internally
  - `async def assign_session(id, session_id)`, `attach_worktree(id, path, branch)`, `record_merge_commit(id, sha)`, `set_commit_message(id, msg)`
  - One method per **intent**, not per column
  - **Landed:** added `repo.transition(id, event, **extra_fields)` (does the get_or_raise + from_columns + transition + to_columns + update_item trio in one call) and `repo.update_fields(id, **fields)` for non-state field writes (rejects column_name/status). Skipped the `assign_session` / `attach_worktree` / `record_merge_commit` specializations — most call sites already pass these as part of a state transition (e.g., `transition(id, START, branch_name=…, worktree_path=…)`); single-purpose helpers can be added later if a clear pattern emerges.
- [x] **2.3** Migrate writes in `workflow_service.py` to repo methods
  - **Landed (combined with 2.2):** all 14 transition call sites in `workflow_service.py` now use `self.items.transition(...)` — 4-line patterns collapse to 1 line each. Dropped `to_columns` and `transition` (function) from the file's imports; `from_columns` retained for `find_stale_worktrees`.
- [x] **2.4** Migrate writes in `web/routes.py` (1504 LOC) to repo methods
  - **Landed:** the one transition call (`retry_merge` endpoint) now uses `orchestrator.item_repository.transition(item_id, Event.RETRY_MERGE)`. Imports trimmed from `Event, from_columns, to_columns, transition` to just `Event`. The DnD `move_item` endpoint and the bulk archive endpoint still write column_name directly via raw SQL — those are deliberate exceptions (the DnD followup is tracked separately; bulk archive is a multi-row optimization). Suite 967 passing.
- [x] **2.5** Delete `ALLOWED_ITEM_COLUMNS` whitelist in `database_service.py`
  - This is the proof the encapsulation closed
  - **Landed:** 4 changes:
    1. The 2 remaining direct `db.update_item` calls in `workflow_service.py` (in `retry_agent` and `cleanup_stale_worktree`) now go through `repo.update_fields`.
    2. `orchestrator._update_item` (legacy compat for integration tests) routes through the repo when no state fields are passed; falls through to `db_service.update_item` when callers explicitly seed `column_name`/`status` for test setup.
    3. `_WRITABLE_ITEM_COLUMNS` moved into `ItemRepository`; both `transition()` and `update_fields()` validate `extra_fields` / `**fields` against it.
    4. Dropped the whitelist + validation block from `database_service.update_item`; it's now a SQL executor that trusts its caller (the repo).
  - Verification: `grep "ALLOWED_ITEM_COLUMNS" src/` returns only doc-comment references explaining the move. The symbol itself is gone.
  - Suite 968 passing.
- [ ] **2.6** Same treatment for `EpicRepository` (smaller, faster — do after items as practice)
- [ ] **2.7** Decide fate of `database_service.py`
  - Becomes the connection / migration owner only, or absorbs into repos? Choose at the end of phase based on what's left.

**Acceptance:** `grep -r "ALLOWED_.*_COLUMNS"` returns nothing. No code outside `repositories/` references item table column names by string.

**Est size:** Phase 2 ≈ 2–3 PRs, ~200 LOC net additions, but big readability win in `workflow_service.py`.

---

### Phase 3 — Kill JSON-string fields in `AgentConfig`

Today: 5 fields typed as `str` that hold JSON (`tools: str = "[]"`, `mcp_servers`, `plugins`, `allowed_commands`, `allowed_builtin_tools`). Every consumer `json.loads()` ad-hoc.

After: real Pydantic types; one parse at the DB boundary.

- [ ] **3.1** Define typed sub-models: `McpServerSpec`, `PluginSpec`, `BuiltinToolSpec`
- [ ] **3.2** Change `AgentConfig` field types to `list[McpServerSpec]` etc.
- [ ] **3.3** Add `field_validator(mode="before")` that calls `json.loads` if the input is a `str`
- [ ] **3.4** Add `model_serializer` (or equivalent) that re-emits JSON strings on the way to SQLite
- [ ] **3.5** Remove every `json.loads(config.tools)` / `json.loads(config.mcp_servers)` etc. from callers — they now get real lists/dicts
- [ ] **3.6** Tests: round-trip a config through DB; assert types are preserved on read

**Acceptance:** `grep -rn "json.loads(.*\.tools)" src/` returns nothing. Same for the other four fields.

**Est size:** 1 PR, ~150 LOC.

---

### Phase 4 — Workspace / Session repositories (drain `workflow_service.py`)

Today: `workflow_service.py` directly orchestrates git worktrees, Claude SDK sessions, and DB rows in 1354 LOC.

After: `workflow_service.py` becomes a coordinator (~400 LOC target) calling three repos.

- [ ] **4.1** `WorkspaceRepository` — owns worktree lifecycle (create, list, prune, detect-stale). Wraps `git/worktree.py` + `git/operations.py`.
- [ ] **4.2** `SessionRepository` — owns Claude SDK session lifecycle (start, pause, resume, kill). Wraps `agent/session.py`.
- [ ] **4.3** Migrate `workflow_service.py` call sites to use the new repos
- [ ] **4.4** Re-evaluate file size of `workflow_service.py`. Target: < 600 LOC. Split further if not.

**Acceptance:** `workflow_service.py` no longer imports `subprocess`, `git`, or Claude SDK directly — only repos.

**Est size:** 2–3 PRs, ~300 LOC net (mostly moves).

---

### Phase 5 (optional) — Discriminated unions per state

Only do this if Phase 1's `StrEnum` still feels too loose in practice. Promote `Item` to a tagged union:

- [ ] **5.1** Define per-state payload classes (`BacklogItem`, `RunningItem(session_id: str)`, `ClarifyingItem(question: ClarificationRequest)`, …)
- [ ] **5.2** `Item = Annotated[Union[…], Field(discriminator="state")]`
- [ ] **5.3** Migrate read paths to `match` on the discriminator
- [ ] **5.4** Optional `Optional` cleanup in repos (e.g., `RunningItem.session_id: str` not `Optional[str]`)

**Acceptance:** in handlers, `match item:` exhaustively covers every state. The compiler/type-checker (mypy/pyright in strict mode) flags missing arms.

**Est size:** 1–2 PRs. Significant churn in template rendering — defer until Phase 1–4 settle.

---

## Working agreement

- **One phase per branch**, ideally one PR per checked box (or a small group).
- After every phase: `./run-tests.sh` green, manual smoke of board UI, then merge.
- If a phase reveals a deeper issue, **stop and re-plan** rather than expanding scope.
- Keep this file updated as the source of truth: tick boxes when landed, add notes inline if a step changed shape.

## How to resume after a break

1. Read this file top-down — checked boxes show what's done.
2. Run `git log --oneline --grep="refactor:"` to see commits per phase.
3. The first unchecked box is the next task.
