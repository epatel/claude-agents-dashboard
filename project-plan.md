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
- [ ] M12 — Code-health pass driven by `aihealth` (status: in progress). One commit per step;
  details of each done step are in its commit message (`git log --grep 'M12 step'`).
  - [x] 0 — Baseline 2026-11-07: 7.14 project (`.aihealth/health.db`, self-ignored), 1434 tests.
  - [x] 1 — `WorkflowService` session-launch dedup (`_launch_session` + helpers). Visible change:
    merge-conflict / permission restarts get `create_shortcut`; `request_changes` uses the item's model.
  - [x] 2 — `approve_item` split into merge phases; new `tests/unit/test_approve_item.py`. Visible
    change: on rebase-then-merge the item broadcast now precedes the dependents notification.
  - [x] 3 — `ClaudeAgentSession.start` → `_build_*` builders, `_receive_loop` dispatch; SDK options
    snapshot byte-identical; live Haiku run. Left: `__init__`'s 35 parameters (shared contract).
  - [x] 4 — `KimiAgentSession._run`, `_parse_plugins`, reviewer, `kimi_board_mcp` split; live Kimi run.
  - [x] 5 — small `src/` dedups (git operations, routes, DB reads, `main()`, file routes, skills).
  - [x] 6 — test dedup via `tests/unit/workflow_fixtures.py` (plain module, NOT a conftest — generic
    fixture names would leak) and `parametrize`; 1441 tests.
  - [ ] 7 — Optional: `.aihealth.toml` + `aihealth scan --fail-under` gate; Swift wrapper files.
  - [ ] 8 — Frontend JS (`src/static/js/`). **Risk:** no JS unit tests; the 7 Node E2E tests spawn
    paid agents (confirm first). Each file was verified with an old-vs-new browser harness on a
    scratch target (dashboard on :8017; harness scripts/baselines in that origin's localStorage,
    `__fb_*` / `__bd_*` / `__an_*`) plus a live check of the UI.
    Done: 8a `file-tree.js` (`FileTreeBase`, shared by both file browsers), 8b file-browser /
    inline-diff splits (dead separator rows removed; CSS `.inline-diff-separator` / `-expand` now
    unused), 8c `board.js`, 8d `annotate.js`, 8e detail / review dialogs (`DialogUtils.fetchItem` /
    `loadWorkLog` / `showTab`), 8f `file-browser.js` 3D / markdown, 8g `spacing_overlay.js` (side
    table + gap helpers; harness: 31 steps of overlay DOM identical), 8h `shortcuts.js` (status
    table, `_save` / `_formFields`, ANSI renderer split into table-driven helpers; harness: 4007
    fuzzed ANSI strings + 47 dialog-flow steps identical; live run), 8i `config-dialog.js`
    (`openConfig` → per-section `_load*`, shared status-dot / model-name / optgroup helpers;
    harness: 62 steps identical; live open + save), 8j `app.js` (`init` → `_wire*` helpers,
    `handleEvent` → `_eventHandlers` table of `_on*` methods, shared log-entry append; harness: 82
    steps identical incl. captured listeners and every WS event type; live WS round trip), 8k
    `item-dialog.js` (`submitItem` / `submitItemAndStart` share `_readItemForm` / `_saveItem` /
    `_saveDepsAndAttachments`, keeping their differences; open paths share `_resetFormState`;
    harness: 24 steps identical; live create + edit through the dialog), 8l `flame.js` (draw
    loop → `_drawFrame` + per-layer helpers; Node replay of 179k recorded 2D-context calls
    identical), `search-dialog.js` (shared `_resultRow`; 26 harness steps identical apart from
    whitespace inside the flex work-log rows), `review-dialog.js` (`ReviewFileBrowser` hunk
    parsing / tab opening / placeholders split; 20k random diffs identical in Node, file-browser
    harness 41/41), 8m `board.js` again (epic panel → `_epicCardHtml` / `_wireEpicPanel`,
    `_groupByEpic`, `_matchesEpicFilter`, `_groupedColumns`, `_startUnlessBlocked`,
    `_insertReviewingBadge`; board harness re-baselined from HEAD — it is date-relative — then
    27/27 identical, plus 21 side-by-side steps for the epic panel / badge / start / loadAndRender),
    8n `annotation-canvas.js` (`saveAnnotation` → `_annotationLayers` list shared by the new-item
    and upload paths; Node replay of 648 cases identical; live save on an empty and a pasted canvas),
    8o `clarification-dialog.js` (`reopenClarification` → `_requestPrefixes` table + `_showPending`;
    command / tool permission prompts share `_showAccessRequest` / `_answerAccessRequest`; Node
    replay of 4884 cases identical bar one console error's wording for a non-string prompt; live
    command / tool / question prompts), 8p `--ui-map` overlays (new `overlay_dom.js`, loaded first:
    `topOpenDialog` / `overlayParent` / `placeIn` / `createBadge` shared by `map_overlay.js`,
    `spacing_overlay.js`, `map_coordinator.js`; harness: old vs new scripts in two iframes, 34 steps ×
    3 initial states identical), 8q `diff.js` (`DiffViewer.renderLine` shared with
    `ReviewFileBrowser._renderDiff`; 3000 random diffs identical side by side, file-browser harness
    41/41), 8r `dialog-utils.js` (`_isOllamaModel` split, its always-true tail dropped; Ollama / Tiiny
    discovery share `_fetchModels` / `_populateModelOptions`, reading the cache by key because
    `config-dialog.js` replaces it; 720 side-by-side cases identical; live item dialog). Every JS
    file is now ≥ 9.56 in a **directory** scan (2026-11-08; the per-file scan misses cross-file
    duplication): lowest `stats.js` 9.56, `api.js` 9.57. `.aihealth.toml` excludes the local untracked `run` script.
  - [x] 9 — Node E2E tests (`tests/e2e/`, 7.41 → 10.00). Never run the agent-spawning ones for real
    without asking (paid agents); verify instead with old-vs-new runs against a fake dashboard API
    through `E2E_PORT`, with the poll/wait constants patched identically in both copies so timeout
    paths finish fast. `test_state_machine_dnd.mjs` and `test_config_roundtrip.mjs` spawn no agent and
    can run for free against `claude-agents-dashboard-e2e-test/`.
    9a `test_merge_conflict.mjs` 5.77 → 10.00 (`main` → phase functions; arrival-order
    `waitForBothReview`). `helpers.mjs` gains `withBoard` (server + browser + teardown), `api*` calls
    (create / start / items / log / approve) and `pollEvery`; `runAgentTask` uses them. 14 fake-API
    scenarios identical in output, exit code and request sequence.
    9b the other six tests onto `withBoard` / `requireTargetRepo` / `api*` (+ `apiRequest` /
    `jsonInit` / `apiGetDiff` / `apiClarify` / `apiGetClarification` / `printAddedLines`);
    `runAgentTask`'s loop → `waitForAgentCompletion` (start elapsed, shared by the clarification
    test); DnD cases and config steps → one function each. 46 fake-API scenarios over all 7 tests
    identical; DnD + config also run for real, old and new, identical and passing.
  - [ ] 10 — Python in `src/` (9.0 at start; worst: `workflow_service.py` 5.71, `skills_service.py`,
    `routes.py`, `kimi_session.py`). Verify with the test suite plus an old-vs-new harness that loads
    the saved old module as `src.services._wf_old` (relative imports still resolve) and drives both
    against the same recording fakes. Done: 10a `workflow_service.py` 5.71 → 7.87 — `on_complete`
    → success / failure handlers + `_has_file_changes` / `_schedule_auto_approve`; `on_create_todo` →
    `_coerce_auto_approve` / `_effective_requires` / `_announce_new_todo` / `_schedule_autostart`;
    `on_view_board`, `peek_worktree`, `_item_session_kwargs`, `find_stale_worktrees` and
    `_run_auto_review` split into helpers (`run_auto_review` is still called from this module — a
    test patches it there); 52 harness cases identical, 1441 tests. Left: file size (next: move
    cohesive groups — session callbacks, peek, auto-review, stale worktrees — out of the file) and
    parameter counts that are public / tool contracts.
  - **Scores** (2026-11-08, after 10a): headline 8.86, src 9.14, JS 9.99, E2E 10.00 (directory scans; `aihealth delta` scores files one at a time, so it cannot see cross-file duplication). aihealth started scanning JS
    mid-pass, so compare like with like (baseline 7.14 had no JS).
  - Pre-existing bugs seen, not fixed: (1) `/api/stats` returns null counts when the work log is
    empty (one all-NULL summary row) → `stats.js` throws every 10 s; (2) the review browser
    auto-expands folders holding changed files without loading their children, so deeper changed
    files stay hidden until the folder is toggled twice; (3) `test_mini_mcp.mjs` still treats
    `config.mcp_servers` as a JSON string (`JSON.parse` on what is now an object throws, is caught,
    and the existing servers are dropped from the PUT).

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

**M12 in flight (2026-11-08): steps 0–6, 8a–8r (JS 9.99) and 9 (E2E tests 10.00) done; step 10 (Python `src/`) in progress; 7 is optional.** `aihealth` is set up for the repo (`.mcp.json`,
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
