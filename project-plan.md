# Project Plan: Claude Agents Dashboard

> Shared source of truth for the **current objective** and the **live state** of the work.
> Every agent (subagent, worktree, or parallel session) reads this first and updates the
> **Current state** and **Decisions** sections before finishing. It is transient and
> goal-oriented — it tracks the moving front of work, not stable architecture. Stable
> knowledge (system topology, conventions, long-lived decisions) lives in
> [`AGENT_FILES/CARDS/`](AGENT_FILES/CARDS/README.md), not here.

## Goal

<!-- Set this to the single north-star outcome of the CURRENT objective, in 1–3 sentences.
     Every agent optimizes toward it; if a task doesn't serve it, the agent stops and flags it.
     When no active objective is in flight, the goal is simply: keep the dashboard correct,
     tested, and shippable on the latest Claude models. -->

**M12 — Code-health pass:** raise the `aihealth` score (baseline **7.14** project, **6.65**
for `src/`, 2026-11-07) by removing duplication and splitting the worst methods, with **no
behavior change** — every step keeps the full test suite green and `aihealth delta` not worse.

## Non-goals

- Refactoring code purely to match an external doc pattern (cards already encode the
  project's own, better-tooled conventions — do not regress them).
- Modifying the **target project / workspace** the dashboard orchestrates; this plan is
  about the dashboard repo itself.
- Expanding scope of a fanned-out task beyond the stated Goal without flagging it here.

## Milestones

- [x] M0 — Baseline: Opus 4.8 default, 24 migrations (001–024), 1035 tests passing, cards current (2026-05-28)
- [x] M1 — Graphify knowledge graph shipped (GraphService + `/api/graphify` + Settings ▸ Graphify tab + `graph_query` MCP tool + post-merge auto-refresh, migration 028); `+advisor` model removed (migration 027); per-task Chrome (025) and `api_error_status` (026) landed (2026-06-06)
- [x] M2 — Docs reassessed and refreshed: README / tests/README / CLAUDE / AGENT_FILES cards updated to 28 migrations (001–028), 1115 tests, 6 services, 8 MCP tools (2026-06-06)
- [x] M3 — Skills library shipped (`SkillsService` + `/api/skills/*` + Settings ▸ Skills tab + migration 029 `enabled_skills` + delivery via SDK `plugins=`); docs reassessed and refreshed to 29 migrations (001–029), 1137 tests, 7 services, 8 MCP tools, new `CARDS/SKILLS.md` (2026-06-06)
- [x] M4 — Kimi Agent SDK runtime (experimental): session-layer refactor (AbstractAgentSession contract + ClaudeAgentSession + provider profiles) then `KimiAgentSession` for `kimi-*` models behind `--experimental`; 1215 tests, new `CARDS/KIMI_PROVIDER.md` (2026-07-18)
- [x] M5 — Kimi parity: commit messages + `ask_user` (marked-line text protocols), board tools (stdio MCP proxy), permission hooks, `create_todo` autostart/requires parity; live-verified (2026-07-18)
- [x] M6 — Claude Opus 5 / Sonnet 5 added, Opus 5 the default (migration 031) (2026-07-25)
- [x] M7 — Cross-worktree peek: `peek_worktree` MCP tool + `GET /api/items/{id}/peek` for Kimi (2026-09-19)
- [x] M8 — Feed-backed model list: `src/model_catalog.py` fetches Claude + Kimi models from the published feed (2026-10-08)
- [x] M9 — Docs reassessment + first security audit of the post-rev-11 subsystems: living docs
  re-verified against code (≈45 wrong test counts, 22 drifted `PROJECT_MAP` anchors, and a set of
  wrong names/flags/claims fixed); `AUDIT.md` rev 12 adds findings #15–#17 (2026-10-08)
- [x] M10 — Hardening pass: Kimi worktree confinement via shared `PathScope` (AUDIT #15 → Mitigated),
  remote skill-install path validation + 8 MiB response cap (#16 → Remediated; audit rev 14, no open
  actionable finding), `verbatim_prompts=True` everywhere, SDK floor `>=0.2.165`, flag-aware
  `run.sh` argument parsing; 1372 tests (2026-10-14)
- [x] M11 — Tiiny provider (experimental): `tiiny/*` models run on a local Tiiny device through its
  Anthropic endpoint as the shared lean *local* profile of the Claude runtime (Ollama profile
  generalized); migration 033, Settings ▸ Tiiny tab, `/api/tiiny/{models,test}`, key from env/Keychain;
  1434 tests; live-verified in the dashboard on a real device (2026-11-06)
- [ ] M12 — Code-health pass driven by `aihealth` (owner: —, status: in progress). One PR per
  step; steps 1→2 and 3→4 are sequential, 5 runs in parallel, 6 waits for 1–5, 8 follows 6.
  - [x] 0 — Baseline (2026-11-07): scan #1 saved to `.aihealth/health.db` (7.14; 73 healthy /
    53 warning / 2 alert); `.aihealth/` self-ignores via its own `.gitignore`; 1434 tests green.
  - [x] 1 — Done 2026-11-07: file 3.17 → 4.73, project 7.14 → 7.25, −178 lines. New helpers
    `_launch_session` / `_session_callbacks` / `_track_yolo` / `_untrack_yolo` /
    `_release_session` / `_request_permission` / `_auto_approvable_item` /
    `_approve_without_review`. Two drifts fixed by unifying: the merge-conflict and
    permission restarts now get the `create_shortcut` tool, and `request_changes` honours the
    item's model (it used the config model). Only `approve_item`'s self-duplication is left (step 2).
    Original scope — `WorkflowService` session-launch dedup (file score 3.17): one `_launch_session`
    helper for `_start_agent_internal` / `resume_agent` / `retry_agent` / `request_changes` /
    `approve_item` / `_restart_session_with_new_permissions` (17–60 shared lines each); merge
    `on_request_command` + `on_request_tool`, `on_complete` + `on_error`, and the shared tail of
    `_auto_approve_no_changes` / `_auto_approve_direct` / `_run_auto_review`.
  - [x] 2 — Done 2026-11-07: file 4.73 → 5.71, project 7.25 → 7.31; `approve_item` has no
    findings left (phases: `_block_merge`, `_dirty_overlap`, `_has_changes_to_merge`,
    `_finish_without_merge`, `_finish_merge`, `_rebase_and_retry_merge`,
    `_restart_for_conflicts`). Added `tests/unit/test_approve_item.py` (7 characterization
    tests, written and passed against the old code first). `peek_worktree` split into
    `_peek_item` / `_peek_overview`. Only visible change: on a rebase-then-merge, the item
    broadcast now precedes the dependents notification, as on the plain merge path. Not done:
    the optional auto-review extraction; the file is still over the Large File limit (1303 LoC).
    Original scope — split `approve_item` (209 lines, cyclomatic 49) into validate → merge → conflicts →
    cleanup/unblock phases; simplify `peek_worktree`. Extracting auto-review into its own
    collaborator is optional — flag here before doing it.
  - [x] 3 — Done 2026-11-07 (live-verified: one real Haiku `ClaudeAgentSession` in a scratch repo
    used who_am_i, Write, Bash past the command filter and set_commit_message; success, $0.04): `session.py` 5.72 → 8.05,
    project 7.31 → 7.38. `start` is now cyclomatic 14 (`_build_mcp_servers`,
    `_build_system_prompt` + note helpers and module-level `_*_NOTE` constants, `_build_allowed_tools`,
    `_build_plugins`, `_build_hooks`, `_build_can_use_tool`, `_stage_attachments`), driven by the
    `_BOARD_SERVERS` / `_BUILTIN_SERVER_TOOLS` tables; `_receive_loop` dispatches to
    `_handle_content_block` / `_handle_result` / `_handle_system_message`; `build_attachment_prompt`
    split. Proof of no behavior change: a snapshot of every SDK option, the full system prompt,
    hooks, `can_use_tool` verdicts and the final query across 6 configs (minimal, full multi-repo +
    attachments + resume, YOLO, bad MCP JSON, Ollama, Tiiny) is byte-identical before/after under a
    fixed `PYTHONHASHSEED` (`OPTIONAL_TOOL_NAMES` is a set, so its whitelist order already varied
    per process). Left: `__init__`'s 35 parameters (the shared session constructor contract).
    Original scope — split `ClaudeAgentSession.start` (391 lines, cyclomatic 91): options building,
    `can_use_tool`, prompt/attachments (`build_attachment_prompt`); flatten `_receive_loop`
    (depth 6) into per-message-type dispatch. Needs a live agent run, not just unit tests.
  - [x] 4 — Done 2026-11-07 (live-verified: one real `KimiAgentSession` on kimi-for-coding in a
    scratch repo streamed thinking + tool calls, wrote a file, ran `ls`, and its commit-message
    marker reached set_commit_message; success): `kimi_session.py` 5.93 → 7.27
    (`_run` → `_handle_permission`, `_open_session`, `_select_model`, `_run_turns` / `_play_turn` /
    `_turn_ended_cleanly`, plus a per-turn `_TurnStream` for chunk buffering and pending tool calls),
    `session_service.py` 6.10 → 7.68 (`_parse_plugins` → bundled / configured / enabled-skill path
    helpers), `review_agent.py` 6.97 → 9.32 (`_collect_review_text`, `_bullet_comments`; both
    `ClaudeAgentOptions` call sites kept), `kimi_board_mcp.py` 7.89 → 10.00 (name → handler table).
    Original scope — split `KimiAgentSession._run` (118 lines) along the same stages; also
    `SessionService._parse_plugins` (cognitive 48), `review_agent._parse_decision` /
    `run_auto_review`, `kimi_board_mcp.call_tool`. Needs a live Kimi run.
  - [x] 5 — Done 2026-11-07: `operations.py` 5.50 → 7.90 (shared `_untracked_files`,
    `_parse_name_status`, `_git_or_empty`, `_resolve_diff_base`; `communicate_or_kill` now also used
    by `GraphService._exec`), `routes.py` 5.70 → 7.07 (`_archive_done_items`, `_item_worktree_root`,
    stats SQL → `_STATS_SUMMARY_SQL` + `_cached_stats` / `_usage_stats`), `database_service.py`
    7.02 → 9.07 (`_fetch_dicts` for six read methods), `main.py` 7.45 → 9.42, `file_routes.py`
    7.35 → 8.86, `skills_service.py` 6.64 → 7.34. **Scoring note:** aihealth was reinstalled
    mid-session (2026-11-07 13:01) and now also scans JavaScript — the 27 `src/static/js/` files
    (5.88) pull the headline project score to 7.21. On the baseline's file set (non-JS) the project
    is 7.64, vs 7.14 at baseline. Compare like with like from here on.
    Original scope — small src dedups: `git/operations.py` (`get_changed_files` / `get_diff`; `run_git`
    vs `GraphService._exec`), `web/routes.py` (archive-by-date/epic, worktree tree/content
    helpers, `_get_optimized_stats`), `database_service.py` query builders, `main()`,
    `file_routes.scan_directory`, `SkillsService._install_sync`.
  - [x] 6 — Done 2026-11-07 (three parallel agents, disjoint files): all six files 3.07–5.68 → 10.00.
    New `test_session_start.py` (31 `start()` tests out of test_session.py), `test_auto_approve.py`
    (15 out of test_workflow_service.py), and `tests/unit/workflow_fixtures.py` — shared WorkflowService
    fixtures as a plain module imported explicitly, NOT a conftest (generic names like `db`/`item`
    would leak). Verified: per-file counts sum to the same 342, full suite 1441, and a runtime count
    of executed asserts (HEAD vs tree) is equal or higher per group. Non-JS project 8.30, tests 8.60.
    Original scope — test duplication via shared fixtures + `parametrize`: `test_create_todo_autostart.py`,
    `test_session.py` (Ollama `TestStart`), `test_workflow_service.py`, `test_diff_mixing.py`,
    `test_allowed_commands.py`, `test_mcp_tool_servers.py`.
  - [ ] 7 — Optional: `.aihealth.toml` + `aihealth scan --fail-under` gate in `make`/CI; Swift
    wrapper (`ProjectManager.swift`, `InstallSheet.swift`, `DashboardTabsView.swift`).
  - [ ] 8 — Frontend JavaScript (`src/static/js/`, 27 files, 5.88; newly scanned by aihealth):
    worst first — `file-browser.js` 3.50 and `review-dialog.js` 4.12 (12 duplication findings
    each), `annotate.js` 4.27 and `board.js` 4.69 (complex / high-cognitive methods), then
    `spacing_overlay.js`, `shortcuts.js`, `config-dialog.js`. Totals: 58 complex methods,
    50 duplications, 41 high-cognitive. **Risk:** the JS has no unit tests — only the 7 Node
    Playwright E2E tests, which spawn real agents (paid; confirm first) — so each file needs a
    browser check of the affected UI (the `run` skill / Chrome) besides the E2E suite. Do this
    after step 6; it does not depend on 7.
    - [x] 8a — 2026-11-07: the two file browsers (`FileBrowser`, `ReviewFileBrowser`) now share
      tree / tab / breadcrumb / filter code via `src/static/js/file-tree.js` (`FileTreeBase`, spread
      into both; per-browser ids/classes in `_tree`, differences as hooks). Verified with a browser
      harness: 30 DOM snapshots (tree, tabs, breadcrumb, content) across both browsers on a scratch
      target, identical to the old code except a trailing space inside one class attribute
      (`classList.toggle` vs `remove`; no rendering effect). file-tree.js 10.00; file-browser.js
      3.50 → 4.86, review-dialog.js 4.12 → 5.43 (scan). Left in those two: `FileBrowser._renderContent`
      / `init` / `_render3DModel` / `_renderArchive`, `ReviewFileBrowser._renderInlineDiff`,
      `ReviewDialog.showReview` (duplicates `DetailDialog.showDetail`).
      8b — 2026-11-07: `ReviewFileBrowser._renderInlineDiff` (137 lines, cyclomatic 41) split into
      `_indexHunkChanges` / `_buildDiffMinimap` / `_changeRuns` / `_attachMinimapViewport`; its
      separator-row branches were dead (the full-file view shows every line) and are gone with
      `_createSeparatorRow` (CSS `.inline-diff-separator` / `.inline-diff-expand` now unused).
      `FileBrowser`: `_renderContent` → `_contentViewer` + `_contentRenderers` table, `init` →
      four `_wire*` methods, `_renderArchive` → header/row builders, `refresh` / `_navigateToDir`
      share `_ensureChildrenLoaded` / `_rerenderTree`. Harness extended to 41 snapshots (multi-hunk
      inline diff, Diff/Full toggle, deleted file, image / binary / zip / .env / STL viewers): all
      identical; minimap click/drag, font controls, keyboard wiring and refresh checked directly.
      file-browser.js → 8.40, review-dialog.js → 6.17. Left: `FileBrowser._render3DModel` (large,
      WebGL — not snapshot-verifiable), `ReviewDialog.showReview` (+ duplication with
      `DetailDialog.showDetail` / `switchDetailTab`). Harness: scratch target + dashboard on :8017,
      script and baseline kept in that origin's localStorage (`__fb_script`, `__fb_baseline`).
      Scores now: headline 7.89, non-JS 8.29, JS 6.63.
      8c — 2026-11-07: `board.js` 4.69 → 8.39. Done/Archive columns share
      `_renderDayGroupedColumn` / `_renderDayGroup` (were 60-line copies); Todo epic and No-Epic groups
      share `_renderTodoGroup`; `renderCard` (cyclomatic 48) → per-part `_card*Html` builders with
      actions split by column (`_todo/_doing/_reviewActionsHtml`); `updateCard` (cyclomatic 36) →
      one rule (re-render the grouped column left, then the one entered, else `_insertCard`).
      Verified with a board harness: ~26 synthetic items covering every card/column branch, rendered
      through the real methods and stepped through collapsing, epic filter, 10 `updateCard` moves,
      removals and unblocking — 27 snapshots × 6 columns identical to the old code; plus the live
      WebSocket create → move → delete round trip. (Board harness: `__bd_script` / `__bd_baseline`
      in the :8017 origin's localStorage.) JS now 7.09, headline 8.00.
      8d — 2026-11-07: `annotate.js` 4.27 → 10.00. `render` → three layer passes over
      `_drawAnnotation` + `_drawCheckerboard` / `_drawImage`; `_drawShape` and `_hitAnnotation` →
      per-type `_shapePainters` / `_annotationHits` tables; text measuring shared (`_measureText`);
      mouse handlers → `_selectAt`, `_resizeImage` (one rule for all four handles), `_dragTo` /
      `_moveShape`, `_shapeFromDrawing` + `_styledAnnotation`; both JPG exports → `_renderJpeg`;
      paste paths → `_firstClipboardImage` / `_firstImageFile`; `_distToLine` takes points.
      Verified with a canvas harness that runs the old copy and the new file in one page through
      49 scripted steps (paste / drop / Clipboard API, select, move, 4-handle resize, wheel, every
      tool on both layers, text create / edit / Escape, drag of each type, delete, exports): pixels,
      model state, a 6-px hit-test grid, export JPGs and return values identical at every step, and
      the recorded 2D-context call log identical except that text sets `textBaseline` after
      measuring instead of before (no pixel effect). Plus real mouse drawing in the dialog.
      JS now 7.82, headline 8.19. Next: `ReviewDialog.showReview` / `DetailDialog` duplication,
      `FileBrowser._render3DModel`, then `spacing_overlay.js`, `shortcuts.js`, `config-dialog.js`.
      Pre-existing bugs seen, not fixed: (1) `/api/stats` returns null counts when the work log is
      empty (the summary query yields one all-NULL row) → `stats.js` throws every 10 s; (2) the review
      browser auto-expands folders holding changed files but doesn't load their children, so changed
      files deeper than the initial tree depth stay hidden until the folder is toggled twice.

## Decisions

Settled, still-relevant choices no agent should reopen without flagging here. Long-lived
architectural rationale graduates to a decision card under `AGENT_FILES/CARDS/`.

- 2026-11-06 — Tiiny is a **local profile of the Claude runtime** (not a separate runtime), using
  the device's Anthropic endpoint. The Ollama `AgentProfile` became the shared local profile
  (`AgentProfile.local`; sessions take `local_env` / `load_claude_md`); the Ollama settings
  (thinking off, `setting_sources=["local"]`) apply to Tiiny unchanged. Tiiny model IDs are
  namespaced `tiiny/<id>` and stripped by `sdk_model_id` before the SDK. The Tiiny API key is
  **never stored in the DB** — `$TIINY_API_KEY`, else macOS Keychain `tiiny-api-key` — and a local
  env is only logged through `redact_env`. Details: `CARDS/TIINY_PROVIDER.md`.

- 2026-10-23 — Python floor is **3.12** (kimi-agent-sdk / kimi-cli declare it; `src/` also uses
  3.11+ `StrEnum` / `asyncio.timeout`). `scripts/python-env.sh` is the only venv bootstrap
  (run.sh, run-tests.sh, `make setup`); the macOS wrapper no longer creates the venv itself.
  It never installs uv or Homebrew on its own — it uses uv only if already present.
  Details: `CARDS/ARCHITECTURE.md` (Entry points & plumbing).
- 2026-10-14 — Path checks have **one** implementation each: `PathScope`
  (`src/agent/path_guard.py`) is the agent worktree boundary for both runtimes, and
  `validate_file_path()` (`src/git/operations.py`) is the string guard for any externally
  supplied relative path joined onto a dashboard-owned directory. Never write a second one;
  they are not interchangeable. Kimi is **Mitigated, not confined** — don't claim otherwise.
  Rationale and details: `CARDS/CONVENTIONS.md` (Security), `CARDS/KIMI_PROVIDER.md`
  ("Worktree confinement"), `CARDS/SKILLS.md`, AUDIT #15/#16. Locked.
- 2026-10-14 — The `claude-agent-sdk` floor tracks the **latest published release** (now
  `>=0.2.165`) because pricing data comes from the SDK. Each bump appends a rev note to
  `AGENT_FILES/SDK_BUMP_2026-06-03.md` (the one append-only exception to the snapshot
  policy). Details: `CARDS/ARCHITECTURE.md` (Entry points & plumbing).
- 2026-10-14 — `run.sh` parses its own args flag-aware; value-taking options live in the
  `--host|--port` case arm and `VALUE_OPTIONS` in `tests/unit/test_run_sh_args.py`. Adding a
  value-taking option to `src/main.py` means adding it to both. Details: `CARDS/ARCHITECTURE.md`.
- 2026-10-14 — Every `ClaudeAgentOptions` passes **`verbatim_prompts=True`** so board-item text
  can't trigger `@path` reads or slash commands. Set it on any new call site. Details:
  `CARDS/ARCHITECTURE.md` (Agent runtime).
- 2026-10-08 — `AGENT_FILES/AUDIT.md` is **revised in place with a new rev** when agent-facing
  surface is added, rather than left as a frozen snapshot like the other root files. Rationale:
  a security doc that says "posture strong, 9 of 9 remediated" while five unreviewed subsystems
  have landed is worse than no doc. Every other root file (`ASSESSMENT_CODE.md`, `PLAN_*`,
  `EVAL_*`, `SDK_BUMP_*`) keeps the don't-touch snapshot policy. A rev must state what it
  reviewed *and* record negative results, so the next reviewer knows what was already cleared.
- 2026-07-25 — Default model is `claude-opus-5` (migration 031); Claude Opus 5 and Claude
  Sonnet 5 added to `AVAILABLE_MODELS`. Supersedes the 2026-05-28 `claude-opus-4-8`
  decision (that model stays selectable). Locked.
- 2026-10-15 — `[1m]` is offered only where it does something: `CLAUDE_1M_OPT_IN_MODELS` is
  `claude-opus-4-6` + `claude-sonnet-4-6`. Per Claude Code's model-config docs, Fable 5/5.1,
  Sonnet 5 and later, Haiku 5.5 and Opus 4.7 and later (so Opus 5 and 5.5 too) run at 1M by
  default. The Opus 5 / 4.8 / 4.7 `(1M)` entries were dropped, and migration 032 strips the
  suffix from stored rows. Amends the 2026-07-25 decision, which had added Opus 5 (1M).
- 2026-10-08 — The selectable Claude and Kimi model lists are **fetched**, not hand-edited:
  `src/model_catalog.py` refreshes it from `constants.MODEL_LIST_URL`
  (`https://epatel.github.io/model-lists/models.json`, non-deprecated entries of providers
  `anthropic` and `kimi-code-plan-global` — the latter prefixed `kimi-code/` to form the Kimi
  CLI alias) at startup and every 6h, serving the bundled `FALLBACK_CLAUDE_MODELS` /
  `KIMI_MODELS` per provider when offline. Ollama (local `/api/tags`) stays local.
  `[1m]` variants come from the local `CLAUDE_1M_OPT_IN_MODELS` set — the feed can't tell
  opt-in from always-1M. Adding a feed provider = a `model_catalog.FEED_PROVIDERS` entry plus a
  runtime/profile for it. `DEFAULT_MODEL` stays a local constant (changing it needs a migration).
- 2026-09-19 — Agents peek at each other's worktrees through the dashboard, never the
  filesystem: the `peek_worktree` MCP tool calls back into `WorkflowService.peek_worktree`,
  which runs the git reads via `GitService`. The `path_guard` hook stays as strict as it
  was — no agent is granted read access outside its own worktree. Locked.
- 2026-05-28 — Extended-thinking budget is 32000 tokens (`src/agent/session.py`). Locked.
- 2026-05-28 — All item state transitions go through the `ItemState` FSM
  (`src/domain/item_state.py`); raw `(column_name, status)` writes outside the SM are a regression. Locked.
- 2026-06-06 — The experimental `+advisor` model suffix is removed (migration 027 strips
  it from stored rows); the session layer no longer parses it. Do not reintroduce the suffix.
- 2026-06-06 — The dashboard owns the graphify knowledge graph (`graphify-out/`); agents get a
  read-only `graph_query` MCP tool only when `graphify_enabled` (migration 028, off by default).
  AST builds/refreshes are free; semantic (LLM) builds cost tokens — run sparingly.
- 2026-06-06 — Agent Skills are dashboard-managed: installed into a gitignored `skill-library/`
  (each wrapped as a one-skill plugin), enabled per-project via `agent_config.enabled_skills`
  (migration 029), and delivered to agents through the SDK `plugins=` option — NOT as an MCP tool.
  Agents run with `setting_sources=["project"]`, so user `~/.claude/skills` are intentionally not used.
- 2026-06-07 — Ollama runs must (a) pass `thinking={"type": "disabled"}` — Ollama returns
  unsigned thinking blocks that crash on replay ("Missing required field … 'signature'") and
  force costly no-resume restarts; and (b) pass an explicit `setting_sources` that excludes
  `user` (we use `["local"]`) so global PreToolUse hooks (e.g. the RTK command-rewriter)
  can't leak in and mangle plain `find`/`ls`/`wc` output. Applies to both `session.py` and
  `review_agent.py`. Do not revert Ollama to "think natively" or to default setting sources.

- 2026-07-18 — Session layer is contract-based: `AbstractAgentSession` (minimal ABC in
  `src/agent/base.py`, chosen over a Protocol for runtime enforcement + conformance tests)
  with `ClaudeAgentSession` (`src/agent/session.py`; `AgentSession` remains as a compat
  alias until a second runtime lands). Ollama is a **profile of the Claude runtime**
  (`src/agent/profiles.py`), not a separate runtime — provider detection, env building,
  and the divergent `ClaudeAgentOptions` values live only there. `ClaudeAgentOptions` is
  still constructed at the call sites (session.py / review_agent.py) so test patch
  targets keep working; the profile supplies kwargs/fields only. Groundwork for a future
  `KimiAgentSession`.
- 2026-07-18 — Kimi is a **separate runtime** (`src/agent/kimi_session.py`), selected
  purely by model id (`kimi-*` → `is_kimi_model`), gated by the `experimental=True` flag
  on its `AVAILABLE_MODELS` entries (no DB flag, no migration). Transport is **ACP**:
  `kimi_agent_sdk.acp.AcpClient` spawns `kimi acp` (CLI >= 0.27.0 on PATH; model via ACP
  `session/set_config_option` — `kimi acp` has no model flag) — chosen over the in-process `prompt()` API to avoid the
  `kimi-cli` version coupling at runtime and to get session/load resume. v1 runs
  `yolo=True` with no dashboard MCP tools/plugins; pause/resume works via the ACP
  session id; auto-review is skipped for Kimi models (Claude-SDK reviewer).
  `kimi-agent-sdk` is installed from the `epatel/kimi-agent-sdk@agentic-setup` fork
  branch in requirements.txt (PyPI lacks the ACP client). Auth via one-time
  `kimi login` (OAuth, shared with the Kimi CLI) or `KIMI_API_KEY` for headless use.
  **Superseded in part by M5**: Kimi no longer runs `yolo=True` — it has a real
  `permission_handler` (`kimi_session.py:340`) plus board tools via the stdio MCP
  proxy. Auto-review is still skipped for Kimi models (the reviewer is a Claude SDK
  session).

## Current state / handoff

**M12 in flight (2026-11-07): steps 0–6 done; next is 8 (frontend JS); 7 is optional.** `aihealth` is set up for the repo (`.mcp.json`,
hooks in `.claude/settings.json`, `## Code health` in CLAUDE.md). Pick the lowest unchecked M12
step whose prerequisites are done, check it off here when its PR lands, and record the new
`aihealth scan .` score. Refactor rules: no behavior change; keep the locked Decisions above
(ItemState FSM for every transition, `ClaudeAgentOptions` built at its call sites so test patch
targets hold, `verbatim_prompts=True`, `PathScope` as the single path check). Line numbers in
`aihealth` output count code lines only — locate functions by name.

Previous change (2026-11-06, M11): Tiiny provider, live-verified on the user's device. The
security audit (`AGENT_FILES/AUDIT.md`, rev 14) has no open actionable finding.

Authoritative counts, re-verified by collection/grep — trust these over prose: **33 migrations
(001–033)**; **1441 tests = 20 smoke + 1407 unit + 14 integration** (plus 7 Node E2E tests,
counted separately); **7 services**; **10 MCP tool servers exposing 12 tools** (`todo.py`
serves three); skills ship as plugins, not as an MCP tool.

⚠️ If 5 tests in `tests/unit/test_allowed_commands.py` fail on `verbatim_prompts`, the venv
has an SDK older than the `>=0.2.165` floor: `./run-tests.sh` reinstalls requirements, a bare
`pytest` does not.

History is not repeated here: see Milestones, the cards for how things work now, and `git log`.

Keep this note a short handoff, not a log.

## Open questions

None open.

An agent that hits a blocker or undecided choice adds it here rather than guessing.
