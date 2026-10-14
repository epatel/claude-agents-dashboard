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

Keep the dashboard correct, well-tested, and shippable on the latest Claude models.
Replace this with the specific objective the moment one is in flight.

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
- [ ] M11 — <next objective — fill in when work is fanned out> (owner: —, status: not started)

## Decisions

Settled, still-relevant choices no agent should reopen without flagging here. Long-lived
architectural rationale graduates to a decision card under `AGENT_FILES/CARDS/`.

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
- 2026-07-25 — Default model is `claude-opus-5` (migration 031); Claude Opus 5, Opus 5 (1M)
  and Claude Sonnet 5 added to `AVAILABLE_MODELS`. Supersedes the 2026-05-28 `claude-opus-4-8`
  decision (that model stays selectable). Locked.
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

No objective in flight. Last change (2026-10-14, M10): the hardening pass — the security audit
(`AGENT_FILES/AUDIT.md`, rev 14) has no open actionable finding. 2026-10-15: agentic setup
refreshed against ai.memention.net/setup (record in `.claude/agent-setup.json`).

Authoritative counts, re-verified by collection/grep — trust these over prose: **31 migrations
(001–031)**; **1372 tests = 20 smoke + 1338 unit + 14 integration** (plus 7 Node E2E tests,
counted separately); **7 services**; **10 MCP tool servers exposing 12 tools** (`todo.py`
serves three); skills ship as plugins, not as an MCP tool.

⚠️ If 5 tests in `tests/unit/test_allowed_commands.py` fail on `verbatim_prompts`, the venv
has an SDK older than the `>=0.2.165` floor: `./run-tests.sh` reinstalls requirements, a bare
`pytest` does not.

History is not repeated here: see Milestones, the cards for how things work now, and `git log`.

The next agent to pick up real work should set **Goal**, fill in **M11**, and rewrite this
note as the running handoff — keep it a short handoff, not a log.

## Open questions

- **Do the 5.5-family models need `[1m]` opt-in entries?** The feed now serves
  `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5` and `claude-fable-5-1`,
  and they are already in `FALLBACK_CLAUDE_MODELS`. None is in
  `CLAUDE_1M_OPT_IN_MODELS`, so none gets a paired `(1M)` entry. For Fable 5.1 that
  is **correct** — it is always 1M on the API, like Fable 5 and Sonnet 5, so the CLI
  exposes no `[1m]` variant. For Opus/Sonnet/Haiku 5.5 it is **unverified**: if any
  of them treats 1M as opt-in the way Opus 5 does, it needs a
  `CLAUDE_1M_OPT_IN_MODELS` entry. Check Claude Code's model-config docs before
  adding one — the feed's `context_window` cannot distinguish opt-in from always-on,
  which is exactly why that set stays a local constant.

An agent that hits a blocker or undecided choice adds it here rather than guessing.
