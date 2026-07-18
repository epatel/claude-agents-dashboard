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
- [ ] M5 — <next objective — fill in when work is fanned out> (owner: —, status: not started)

## Decisions

Settled, still-relevant choices no agent should reopen without flagging here. Long-lived
architectural rationale graduates to a decision card under `AGENT_FILES/CARDS/`.

- 2026-05-28 — Default model is `claude-opus-4-8` (migration 024). Locked.
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
  `kimi_agent_sdk.acp.AcpClient` spawns `kimi acp` (CLI >= 0.27.0 on PATH; model via
  `KIMI_MODEL_NAME` env) — chosen over the in-process `prompt()` API to avoid the
  `kimi-cli` version coupling at runtime and to get session/load resume. v1 runs
  `yolo=True` with no dashboard MCP tools/plugins; pause/resume works via the ACP
  session id; auto-review is skipped for Kimi models (Claude-SDK reviewer).
  `kimi-agent-sdk` is installed from the `epatel/kimi-agent-sdk@agentic-setup` fork
  branch in requirements.txt (PyPI lacks the ACP client). Auth via one-time
  `kimi login` (OAuth, shared with the Kimi CLI) or `KIMI_API_KEY` for headless use.

## Current state / handoff

Docs reassessed 2026-06-06 (M3). No objective currently in flight. Since the M2 docs
refresh the codebase added the **skills library**: a seventh service (`SkillsService`),
migration 029 (`agent_config.enabled_skills`), the `/api/skills/*` endpoints, a Settings ▸
Skills tab, and per-project skill delivery via the SDK `plugins=` option. Authoritative
counts are now **30 migrations (001–030), 1174 tests (unit / integration /
smoke), 7 services, 8 built-in MCP tools** (skills ship as plugins, not as an MCP tool).
README, tests/README, CLAUDE.md, and all `AGENT_FILES/CARDS/` were re-audited against the
code and corrected; a new `CARDS/SKILLS.md` card documents the subsystem and is wired into
the routing manifest. The dated snapshots in `AGENT_FILES/` root (AUDIT, ASSESSMENT_CODE,
EVAL_*, PLAN_*, SDK_BUMP_*) are point-in-time records and were intentionally left untouched.
Re-audit 2026-07-15 (`/review-agentic-setup`): migration `030`
(`agent_config.ollama_load_claude_md`) landed and tests grew 1137 → 1174 — counts above
refreshed; `src/constants.py` now also offers Claude Fable 5 as a selectable model while
the default stays `claude-opus-4-8` per the locked decision.
Refactor 2026-07-18 (branch `refactor/agent-session-contract`): the session layer was
prepared for a second agent runtime (Kimi Agent SDK, not yet started). New
`src/agent/base.py` (`AbstractAgentSession` + `AgentResult`) and `src/agent/profiles.py`
(provider routing + `AgentProfile`); `AgentSession` renamed to `ClaudeAgentSession`;
the scattered `is_ollama` conditionals and duplicated env builders/predicates in
`session.py`, `review_agent.py`, `session_service.py`, `workflow_service.py` collapsed
onto the profile. No behavior change; tests grew 1174 → 1195 (new
`tests/unit/test_base.py`, `tests/unit/test_profiles.py`). Cards updated:
ARCHITECTURE, OLLAMA_PROVIDER, PROJECT_MAP (flow.agent-start), TESTING.

M4 (same day, merged to main): **KimiAgentSession** landed as the first non-Claude
runtime and was then switched to the **ACP transport** — `AcpClient` spawning
`kimi acp` instead of the in-process `prompt()` API (drops the runtime `kimi-cli`
coupling, adds session/load pause-resume). Routing in `SessionService` via
`is_kimi_model`, `kimi-k2` / `kimi-k2-turbo` as experimental `AVAILABLE_MODELS`
entries, auto-review guard in `workflow_service`, Kimi provider badge in the
frontend; `kimi-agent-sdk` 0.0.6 installed via requirements.txt from the
`agentic-setup` fork branch (verified in venv; pulled pydantic 2.13.1 → 2.12.5).
Tests now **1218** (`tests/unit/test_kimi_session.py` rewritten for ACP);
`CARDS/KIMI_PROVIDER.md` registered in the manifest. `AVAILABLE_MODELS` carries the
real kimi-code aliases (`kimi-code/k3`, `kimi-code/kimi-for-coding[-highspeed]` —
verified against `kimi provider list`), and model selection goes through ACP
`session/set_config_option` (as flutter_kimi_sdk does; `kimi acp` has no model flag).

**Live smoke run passed 2026-07-18** (kimi CLI 0.27.0, `kimi login` auth, scratch
target repo, `--experimental`): a `kimi-code/k3` card routed to `KimiAgentSession`,
spawned `kimi acp`, model selection accepted, streamed Read/Edit/Bash tool calls +
final message to the work log, produced a correct minimal diff, and landed in Review
with the ACP session id stored (pause/resume live). Known cosmetic gap: tool-call log
entries show an empty input — kimi-code doesn't populate `rawInput` on the initial
`tool_call` update; surfacing `ToolCallProgress` detail would fix it. Also still open:
commit-message / ask_user equivalents for Kimi agents.
The next agent to pick up real work should set **Goal**, add an **M5** milestone, and
update this note as the running handoff.

## Open questions

- None currently. An agent that hits a blocker or undecided choice adds it here rather
  than guessing.
