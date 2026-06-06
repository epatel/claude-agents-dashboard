# PLAN: Graphify capability — implementation

Companion to [`EVAL_graphify_capability_2026-06-06.md`](EVAL_graphify_capability_2026-06-06.md) (feasibility + rationale). This file is the actionable build plan. Status: **planned, not started.**

## Locked decisions

1. **Graph lives in `<target_project>/graphify-out/`**, and the dashboard adds `graphify-out/` to the target's `.gitignore` (mirroring the `agents-lab/` handling in `src/main.py:156-179`). Never committed into the target's history. (`graph.json` = truth; `graph.html`/`GRAPH_REPORT.md`/`cache/` = derived.) **Correction (verified empirically during Phase 1):** the original plan said `agents-lab/graphify-out/`, but `graphify update <path>` always writes to `<path>/graphify-out/` (ignores cwd, no `--out`), and even `extract --out` leaks a `cache/` into the scan root — so the tool dictates the scan-root location. `GraphService._ensure_gitignore()` keeps it out of git instead.
2. **The server is the sole writer.** A new `GraphService` shells out to `venv/bin/graphify` (pinned, not PATH — per `AGENT_FILES/CARDS/GRAPHIFY.md`). Agents never write the graph.
3. **Agents read via a `graph_query` MCP tool** (native pattern, like `view_board`/`ask_user`) — no files in the worktree, no `path_guard` exception.
4. **Freshness is merge-reactive and free:** after an item merges to root, the server runs incremental `graphify update` (AST-only, no LLM). Semantic enrichment (~230k tokens) is explicit opt-in.
5. **Two UI surfaces:** Settings ▸ Graphify tab (lifecycle/management) is v1; a top-bar Graph *viewer* dialog is a deferrable follow-up.
6. **State split:** `graphify_enabled` / `graphify_auto_refresh` / `graphify_backend` are saved `AgentConfig` fields; install/upgrade/build/status are imperative server endpoints (the Ollama-section pattern), not config values.

---

## Phase 1 — GraphService + status/build backend (foundation)

Goal: server can build, refresh, query, and report on the graph. No UI yet.

- [x] `src/services/graph_service.py` — new service (6th, sibling to the 5 in `src/services/`). Methods, all via `asyncio.create_subprocess_exec` (**arg list, never `shell=True`**), running `sys.executable -m graphify` (venv interpreter):
  - `status()` → `{installed_version (importlib.metadata), latest_version (cached PyPI lookup), building, graph: {exists, nodes, edges, communities, built_at_commit, last_built, cost}, graph_dir}`. Reads `<target>/graphify-out/{graph.json, cost.json}`; stats cached by graph.json mtime.
  - `build(semantic: bool)` → `graphify update <root>` (AST, free) or `graphify extract <root> [--backend gemini]` (semantic). Serialized by a lock; broadcasts progress.
  - `refresh()` → AST `build(semantic=False)`, never raises (the merge-reactive call).
  - `query(q)` / `path(a,b)` / `explain(x)` → `graphify <cmd> ... --graph <target>/graphify-out/graph.json`. Read-only; guard when no graph yet.
  - `install()` → `sys.executable -m pip install --upgrade graphifyy` (privileged; see risks).
  - `_ensure_gitignore()` → adds `graphify-out/` to the target `.gitignore` (single-repo only).
  - Build **lock**: concurrent build rejected (`already_building`) so they can't clobber `graph.json`.
- [x] Resolve the target/workspace root from the orchestrator (`target_project`, `repos`) like the other services.
- [x] Wire `GraphService` into `AgentOrchestrator` (`src/agent/orchestrator.py:48`); reachable via `request.app.state.orchestrator.graph_service`.
- [x] Endpoints in `src/web/routes.py` (after the config endpoints):
  - `GET  /api/graphify/status`
  - `POST /api/graphify/build`  (body `{semantic: bool}`; background task, returns immediately)
  - `POST /api/graphify/install`
  - `GET  /api/graphify/query?q=...`
- [x] Progress over the existing WS fan-out — `NotificationService.broadcast_graph_event()` → `graph_build_progress` / `graph_ready`.
- [x] Tests: `tests/unit/test_graph_service.py` (12) + `tests/unit/test_routes.py::TestGraphify` (7). Assert argv/no-shell, lock, stats parsing, query passthrough. Full suite: 1067 passing.

**Phase 1 complete.** Remaining for the feature: Phase 2 (Settings tab + migration), Phase 3 (graph_query MCP tool), Phase 4 (auto-refresh on merge).

## Phase 2 — Settings ▸ Graphify tab (v1 surface) — COMPLETE

Goal: a human can enable, install/upgrade, build, and see status/cost.

- [x] **DB migration** `src/migrations/versions/028_add_graphify_config.py`: adds `agent_config` columns `graphify_enabled INTEGER DEFAULT 0`, `graphify_auto_refresh INTEGER DEFAULT 1`, `graphify_backend TEXT DEFAULT 'ast'`. `down()` is a no-op (matches recent column-add migrations).
- [x] `src/models.py::AgentConfig` — added the three fields. (No whitelist change needed: `agent_config` writes go through the explicit `UPDATE` in `PUT /api/config`, and `get_agent_config` uses `SELECT *`, so new columns flow through automatically.)
- [x] `GET/PUT /api/config` — GET auto-includes them (`SELECT *`); PUT's explicit `UPDATE` extended with the three columns.
- [x] `src/templates/board.html` — Graphify tab button (after Plugins) + `data-config-tab="graphify"` pane: status line, conditional Upgrade button, enable / auto-refresh toggles, backend select, Build/Enrich buttons.
- [x] `src/static/js/config-dialog.js`: `openConfig()` loads the three fields + calls `refreshGraphifyStatus()`; `submitConfig()` sends them; new `refreshGraphifyStatus()` / `installGraphify()` (confirm) / `buildGraph(semantic)` (token-cost confirm for semantic).
- [x] `src/static/js/app.js` — handles `graph_build_progress` / `graph_ready` → refreshes the tab status if open.
- [x] Tests: `tests/unit/migrations/test_graphify_config_028.py` (3) + `test_routes.py::TestConfig::test_graphify_fields_round_trip`. Full suite: 1071 passing.

(Used `Api.request()` directly from config-dialog.js rather than adding `api.js` helpers — consistent with how the dialog already calls `/api/config`.)

**Phase 2 complete.** Remaining: Phase 3 (graph_query MCP tool), Phase 4 (auto-refresh on merge).
- [ ] Tests: route tests for the new endpoints (`tests/unit/test_routes.py` style); migration test under `tests/unit/migrations/`.

## Phase 3 — graph_query MCP tool (agent consumption) — COMPLETE

Goal: agents can orient against the graph, gated by `graphify_enabled`.

- [x] `src/agent/graph_query.py` — MCP tool server exposing `graph_query` (takes `{question}`). Pattern mirrors `src/agent/board_view.py`.
- [x] Wired through the stack: `AgentSession` gains `on_graph_query` + `graphify_enabled` and registers the server / permits `mcp__graph_query__graph_query` / adds a system-prompt hint **only when `graphify_enabled` and not Ollama**; `SessionService.create_session` forwards both from config; `WorkflowService._create_on_graph_query_callback()` (delegating to `GraphService.query`) is passed at all 6 call sites; `AgentOrchestrator` passes `graph_service` into `WorkflowService`.
- [x] Tests: `tests/unit/test_graph_query_tool.py` (7) — server builds, session stores/defaults the fields, callback returns answer / surfaces errors / handles missing graph_service. Full suite: 1077 passing.

**Phase 3 complete.** Remaining: Phase 4 (auto-refresh on merge), Phase 5 (optional viewer / semantics / multi-repo).

## Phase 4 — Auto-refresh on merge — COMPLETE

Goal: graph tracks mainline with zero token cost and zero agent involvement.

- [x] `WorkflowService._maybe_refresh_graph_after_merge()` — fires `GraphService.refresh()` as a fire-and-forget task on both successful-merge branches of `approve_item` (direct merge + rebase-retry). Gated on `graphify_auto_refresh` **and an existing `graph.json`** — it maintains an opted-in graph but never silently builds one (initial build stays the Settings-tab action). Free AST; serialized by GraphService's build lock; the `graph_ready` WS event already refreshes the Settings tab.
- [~] UI staleness hint: deferred — `built_at_commit` is already surfaced in status; the live `graph_ready` refresh keeps the tab current, so an explicit dirty marker is a nice-to-have for later.
- [x] Tests: `tests/unit/test_graph_query_tool.py::TestAutoRefreshOnMerge` (4) — refreshes when enabled+graph-exists, skips when disabled / no graph / no graph_service. Full suite: 1081 passing.

**Phase 4 complete.** Remaining: Phase 5 (optional viewer dialog / semantic polish / multi-repo).

## Phase 5 — Optional follow-ups

- [ ] **Graph viewer dialog** (top-bar "Graph" button): `graph-dialog.js` + `<dialog id="graph-dialog" class="modal modal-large">`, tabs Overview (god nodes/communities/questions from `GRAPH_REPORT.md`) / Graph (`<iframe src="/api/graphify/html">`, serve `graph.html`) / Query.
- [ ] **Semantic enrichment polish**: Gemini backend when `GEMINI_API_KEY` set, else cost-warning; surface `cost.json` cumulative.
- [ ] **Multi-repo**: per-repo graphs + `graphify merge-graphs` into a workspace graph.

---

## Cost & risk (carry-over from EVAL)

| Risk | Mitigation |
|---|---|
| Semantic rebuild ≈ 230k tokens | AST default; semantic behind a cost-confirm dialog; per-file-hash cache |
| `install`/`build` mutate host / cost time | background tasks + confirms; never block requests |
| Shell injection via query | `create_subprocess_exec` arg list, no shell |
| `graphify` only in venv | GraphService pins `venv/bin/graphify` |
| Concurrent builds clobber graph.json | GraphService build lock + coalesced refreshes |
| New config columns | migration + model field + whitelist; no raw column writes |

## Sequencing & estimate

Phase 1 → 2 → 3 → 4 is the dependency order (each builds on the prior). Rough: P1 ~1d, P2 ~1d, P3 ~0.5d, P4 ~0.5d → **~3 days to a usable managed capability**; Phase 5 adds ~1.5d for the polished viewer + semantics.

## Open items for the human

1. Default `graphify_backend` — ship `ast` (free) as default? (recommended yes)
2. Is the Settings tab enough for v1, or is the Graph viewer wanted in the first cut?
3. Multi-repo graph location/strategy — defer to Phase 5 or needed sooner?
