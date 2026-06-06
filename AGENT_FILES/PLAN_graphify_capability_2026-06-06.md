# PLAN: Graphify capability — implementation

Companion to [`EVAL_graphify_capability_2026-06-06.md`](EVAL_graphify_capability_2026-06-06.md) (feasibility + rationale). This file is the actionable build plan. Status: **planned, not started.**

## Locked decisions

1. **Graph lives in `agents-lab/graphify-out/`** — the existing dashboard data dir, already gitignored in the target repo (`src/main.py:156-179`). Never committed into the target's history. (`graph.json` = truth; `graph.html`/`GRAPH_REPORT.md`/`cache/` = derived.)
2. **The server is the sole writer.** A new `GraphService` shells out to `venv/bin/graphify` (pinned, not PATH — per `AGENT_FILES/CARDS/GRAPHIFY.md`). Agents never write the graph.
3. **Agents read via a `graph_query` MCP tool** (native pattern, like `view_board`/`ask_user`) — no files in the worktree, no `path_guard` exception.
4. **Freshness is merge-reactive and free:** after an item merges to root, the server runs incremental `graphify update` (AST-only, no LLM). Semantic enrichment (~230k tokens) is explicit opt-in.
5. **Two UI surfaces:** Settings ▸ Graphify tab (lifecycle/management) is v1; a top-bar Graph *viewer* dialog is a deferrable follow-up.
6. **State split:** `graphify_enabled` / `graphify_auto_refresh` / `graphify_backend` are saved `AgentConfig` fields; install/upgrade/build/status are imperative server endpoints (the Ollama-section pattern), not config values.

---

## Phase 1 — GraphService + status/build backend (foundation)

Goal: server can build, refresh, query, and report on the graph. No UI yet.

- [ ] `src/services/graph_service.py` — new service (6th, sibling to the 5 in `src/services/`). Methods, all via `asyncio.create_subprocess_exec` (**arg list, never `shell=True`** — query text is user input):
  - `status()` → `{installed_version, latest_version (cached PyPI lookup), graph: {exists, nodes, edges, communities, last_built, cost}}`. Reads `agents-lab/graphify-out/{graph.json, cost.json}`.
  - `build(semantic: bool)` → `graphify extract <root> --out agents-lab/` (semantic) or `graphify update <root>` writing into `agents-lab/graphify-out/` (AST). Runs detached; emits progress.
  - `refresh()` → incremental AST `update` (the merge-reactive call).
  - `query(q)` / `path(a,b)` / `explain(x)` → `graphify query "<q>" --graph agents-lab/graphify-out/graph.json` etc. Read-only.
  - `install()` → `venv/bin/pip install --upgrade graphifyy` (privileged; see risks).
  - Internal: a build **lock** so concurrent builds can't clobber `graph.json`; coalesce queued refreshes.
- [ ] Resolve the target/workspace root the same way `main.py` does for `agents-lab/` (single + multi-repo).
- [ ] Wire `GraphService` into `AgentOrchestrator` (`src/agent/orchestrator.py`) or expose directly to routes — match how the other services are surfaced.
- [ ] Endpoints in `src/web/routes.py` (or new `src/web/graph_routes.py` if it keeps routes.py lean):
  - `GET  /api/graphify/status`
  - `POST /api/graphify/build`  (body `{semantic: bool}`; returns immediately, streams progress)
  - `POST /api/graphify/install`
  - `GET  /api/graphify/query?q=...`
- [ ] Progress over the existing WS fan-out (`NotificationService` → `src/web/websocket.py:133`): broadcast `graph_build_progress` / `graph_ready`.
- [ ] Tests (`tests/unit/test_graph_service.py`): mock subprocess; assert arg lists (no shell), lock behavior, status parsing, query passthrough. Per `AGENT_FILES/CARDS/TESTING.md`.

## Phase 2 — Settings ▸ Graphify tab (v1 surface)

Goal: a human can enable, install/upgrade, build, and see status/cost.

- [ ] **DB migration** `src/migrations/versions/028_*.py` (next after 027): add `agent_config` columns `graphify_enabled INTEGER DEFAULT 0`, `graphify_auto_refresh INTEGER DEFAULT 1`, `graphify_backend TEXT DEFAULT 'ast'`. Implement `up()`/`down()`.
- [ ] `src/models.py::AgentConfig` — add the three fields (validators tolerant of raw values, per existing pattern). Add to the agent-config **write whitelist** wherever `agent_config` columns are gated (mirror `_WRITABLE_*` discipline; **no raw column writes**).
- [ ] `GET/PUT /api/config` — include the new fields in load + save.
- [ ] `src/templates/board.html` — add tab button after Plugins (`board.html:417`) and a `data-config-tab="graphify"` pane (clone the Ollama pane `board.html:469` for the status-dot + action-button shape). Default-hidden, `data-map-name` annotations for the project-map.
- [ ] `src/static/js/config-dialog.js`:
  - In `openConfig()`: load the three fields; call a new `refreshGraphifyStatus()` (mirrors `refreshOllamaModels()` → status dot + version + counts via `/api/graphify/status`).
  - In `submitConfig()`: add the three fields to the `config` payload.
  - New actions: `installGraphify()` → confirm (reuse `toggleYolo` confirm pattern) → `POST /api/graphify/install`; `buildGraph(semantic)` → `POST /api/graphify/build` (semantic path shows a token-cost confirm).
- [ ] `src/static/js/api.js` — add `getGraphifyStatus()`, `buildGraph()`, `installGraphify()`.
- [ ] `src/static/js/app.js` — handle `graph_build_progress`/`graph_ready` WS events → update the tab's status line.
- [ ] Tests: route tests for the new endpoints (`tests/unit/test_routes.py` style); migration test under `tests/unit/migrations/`.

## Phase 3 — graph_query MCP tool (agent consumption)

Goal: agents can orient against the graph, gated by `graphify_enabled`.

- [ ] `src/agent/graph_query.py` — MCP tool server exposing `graph_query` (and optionally `graph_path`, `graph_explain`). Each calls `GraphService` read methods. Pattern: copy `src/agent/board_view.py` (`view_board`).
- [ ] Wire into `SessionService`/`session.py` tool assembly **only when `graphify_enabled`** is set on the config. Add a one-line system-prompt note ("Before editing, query the code graph to orient") like other tool hints.
- [ ] Tests: tool present iff enabled; query passthrough returns graph answer.

## Phase 4 — Auto-refresh on merge

Goal: graph tracks mainline with zero token cost and zero agent involvement.

- [ ] In `WorkflowService` at the approve→merge seam (after a successful merge to root), if `graphify_auto_refresh`, call `GraphService.refresh()` (fire-and-forget background task; WS progress). Serialize via the GraphService lock.
- [ ] UI staleness hint: status shows "last built @ commit" + dirty marker if HEAD moved since.
- [ ] Tests: merge triggers exactly one refresh; refresh is non-blocking; lock coalesces.

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
