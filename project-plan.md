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

No active objective (M12 finished 2026-11-08): keep the dashboard correct, tested, and
shippable on the latest Claude models, without letting the `aihealth` scores fall below the
`run-tests.sh` floors.

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
- [x] M12 — Code-health pass driven by `aihealth` (2026-11-07 → 11-08): project 7.14 → 9.77
  (`src/` 9.72, tests 9.89, macOS wrapper 9.88, JS 9.99, E2E 10.00; directory scans). No behavior
  change; 42 commits, one per step — details in `git log --grep 'M12 step'`. Held by the
  `run-tests.sh` health gate (step 7). How each step was verified (old-vs-new harnesses):
  `CARDS/TESTING.md` ("Behavior-preserving refactors").
  - Left on purpose: the shared session `__init__` contracts (35 / 15 parameters),
    `_tiiny_request`'s 5 positional parameters (tests
    read `call_args`), `orchestrator.py` 8.51 (app facade + legacy helpers integration tests use).
  - The 4 pre-existing bugs seen during M12 were fixed on 2026-11-13 (`git log`).

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

**No milestone in flight.** M12 (code-health pass) finished 2026-11-08; after it, `create_todo`
got a keyword contract, `run.sh` / the macOS wrapper got exit-handling fixes, and the four
known bugs from M12 were fixed (2026-11-13; see `git log`).
Refactor rules still apply: no behavior change; keep the locked Decisions above (ItemState FSM,
`ClaudeAgentOptions` built at its call sites, `verbatim_prompts=True`, `PathScope`). Line
numbers in `aihealth` output count code lines only — locate functions by name.

Previous change (2026-11-06, M11): Tiiny provider, live-verified on the user's device. The
security audit (`AGENT_FILES/AUDIT.md`, rev 14) has no open actionable finding.

Authoritative counts, re-verified by collection/grep — trust these over prose: **33 migrations
(001–033)**; **1450 tests = 20 smoke + 1416 unit + 14 integration** (plus 7 Node E2E tests,
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
