# EVAL: Graphify capability for claude-agents-dashboard (2026-06-06)

Status: **proposal / feasibility** — not yet decided or implemented.

## Goal

Give the dashboard a "knowledge graph" capability over the target project (single-repo) or workspace (multi-repo), powered by [graphify](https://graphify.net/) (PyPI `graphifyy`, currently pinned to 0.8.33 in `venv/`). Two surfaces were requested:

1. A `plugins/` part — make graphify available to the agents the dashboard orchestrates.
2. Some UI — let the human view/query the graph from the dashboard.

These are **two separable tracks** with different value, effort, and risk. They can ship independently.

---

## Track A — Graphify as a dashboard plugin (agent-facing)

### What it is
A Claude Code plugin under `plugins/graphify/`, auto-discovered exactly like `board-workflows`. Gives every agent the `/graphify` skill so an agent can build or query a knowledge graph of the code it's working on as part of its task.

### How it would wire in (verified against current code)
- Auto-discovery already exists: `SessionService._parse_plugins()` (`src/services/session_service.py:232-271`) scans `plugins/` for any dir with `.claude-plugin/plugin.json` and passes it to the SDK as `{"type":"local","path":...}` (`src/agent/session.py:400-410, 513/529`). **Dropping a plugin dir in `plugins/` requires zero backend wiring.**
- Structure to add:
  ```
  plugins/graphify/
    .claude-plugin/plugin.json        # {name, version, description}
    skills/graphify/SKILL.md          # the skill body
  ```

### Feasibility: MEDIUM, with real caveats
- **Dependency availability.** The agent's runtime must be able to invoke graphify. Agents run with the target worktree as cwd, not the dashboard venv. Options: (a) the SKILL bootstraps install (`uv tool install graphifyy` / `pip install`), which the upstream skill already does in Step 1; (b) require graphify preinstalled. (a) is more robust but slower/first-run heavy.
- **Subagent dispatch.** The upstream full `/graphify` pipeline dispatches **its own Agent subagents** for semantic extraction. Nested agent dispatch inside an SDK-driven agent is unproven here and risks runaway token use. **Mitigation: ship a constrained skill that defaults to `graphify update .` (AST-only, deterministic, no LLM, free)**, with full semantic extraction available only via an explicit flag.
- **Worktree ephemerality.** `graphify-out/` written inside an agent's git worktree is isolated and discarded on cleanup unless committed/merged. So an agent-built graph is transient — fine for "agent reasons about structure mid-task", useless as a persistent dashboard artifact. This is the core reason Track B is the better home for a *persistent* graph.
- **Ollama mode** skips plugins entirely (`session.py:409`), so this is Claude-only.

### Effort
- Thin AST-only skill + manifest: ~0.5 day.
- Robust skill with install bootstrap + Gemini-backed semantic option: ~1.5 days.

---

## Track B — Server-side graph feature + UI (human-facing) — RECOMMENDED PRIMARY

### What it is
The **dashboard server itself** builds and serves a persistent knowledge graph of the target project by shelling out to `venv/bin/graphify` (already installed, 0.8.33). The graph lives in `graphify-out/` at the target/workspace root (next to the existing `agents-lab/`), independent of agent worktrees. A new UI panel views and queries it.

Why server-side beats agent-driven for the persistent graph: controllable cost, deterministic location, no worktree/subagent issues, available even with no agent running, and it reuses the binary we already maintain (see `AGENT_FILES/CARDS/GRAPHIFY.md`).

### Backend (maps to existing patterns)
- New `GraphService` (sibling to the 5 services in `src/services/`) that wraps the CLI with `asyncio.create_subprocess_exec` (**arg list, never `shell=True`** — query text is user input):
  - `update()` → `graphify update <root>` (AST refresh, free, no LLM) — the default build
  - `query(q)` → `graphify query <q>` (BFS, cheap)
  - `path(a,b)`, `explain(x)` — graph navigation
  - readers for `graphify-out/{graph.json, GRAPH_REPORT.md, cost.json}`
- Endpoints in `src/web/routes.py` (follows `@router` + `Api.request` pattern):
  - `GET  /api/graph/status` — exists?, node/edge/community counts, last-built, cumulative token cost
  - `POST /api/graph/build` — kick off build as a background task; stream progress over WS
  - `GET  /api/graph/report` — parsed god-nodes / communities / suggested-questions
  - `GET  /api/graph/query?q=...` — traversal answer
  - `GET  /api/graph/html` — serve the self-contained `graph.html`
- Long build → run detached, broadcast `graph_build_progress` / `graph_ready` via `NotificationService` WS fan-out (`src/web/websocket.py:133-142`), exactly like agent log broadcasts.

### Frontend (maps to existing patterns)
- Top-bar button **"Graph"** next to Search/Files/Settings (`base.html:28-77`).
- New dialog: `<dialog id="graph-dialog" class="modal modal-large">` in `board.html` + `src/static/js/graph-dialog.js` (`{open, close}` namespace), registered in `dialogs.js`, script tag in `base.html` before `dialogs.js` — the documented "add a dialog" recipe.
- Tabs inside it (reuse `.review-tab` pattern from `detail-dialog.js:268`):
  - **Overview** — god nodes, communities, suggested questions (from `/api/graph/report`)
  - **Graph** — `<iframe src="/api/graph/html">` (self-contained, no extra deps)
  - **Query** — input box → `/api/graph/query` → rendered answer with `source_location` citations
- `api.js` methods + an `app.js` WS case for build progress.

### Feasibility: HIGH
- Every required mechanism already exists (services layer, background tasks, WS broadcast, dialog/tab system, static serving). No new infra.
- Main UX risk: the ~3MB self-contained `graph.html` in an iframe — acceptable for an on-demand modal; for very large graphs graphify already auto-aggregates to a community view above 5000 nodes, and `--no-viz` is available.

### Effort (phased)
- **Phase 0 (~1 day):** read-only — `GraphService` + `/api/graph/status`, `/report`, `/html`; "Graph" button + dialog with Overview tab and the iframe, *if `graphify-out/` already exists*. Immediate value, zero build cost.
- **Phase 1 (~1 day):** `POST /api/graph/build` (AST `update`, free) with WS progress + "Rebuild" button.
- **Phase 2 (~0.5 day):** Query tab (`graphify query`).
- **Phase 3 (~1 day, optional):** semantic/full rebuild opt-in (Gemini backend if `GEMINI_API_KEY` set, else cost warning) + multi-repo cross-graph merge.

---

## Cost & risk

| Concern | Detail | Mitigation |
|---|---|---|
| **Token cost** | Full semantic rebuild ≈ 230k output tokens (measured this repo). | Default to AST-only `update` (free). Semantic = explicit opt-in, surface `cost.json` in UI. |
| **Build latency** | Semantic build is minutes; AST build is seconds. | Background task + WS progress; never block a request. |
| **Shell injection** | Query text → CLI. | `create_subprocess_exec` with arg list, no shell. |
| **Staleness** | Graph drifts from code. | Show "last built" + dirty hint; optional post-merge auto `update` (graphify ships a git hook). |
| **Worktree isolation** (Track A) | Agent-built graph is ephemeral. | Persistent graph is server-side (Track B). |
| **Multi-repo** | Graph location ambiguous across sibling repos. | Phase 3: per-repo graphs + `graphify merge-graphs`. |
| **Binary drift** | `graphify` only in `venv`, not PATH. | Already documented in `GRAPHIFY.md`; GraphService pins `venv/bin/graphify`. |

---

## Open decisions (need a human call)

1. **Primary trigger model** — server-side button (Track B), agent plugin (Track A), or both? *Recommendation: ship Track B Phase 0–2 first; add Track A later as opt-in.*
2. **Default extraction depth** — AST-only (free) vs full semantic (~230k tokens). *Recommendation: AST-only default, semantic opt-in behind a cost-confirming dialog.*
3. **Graph lifecycle** — manual rebuild only, or auto-refresh on merge/commit? Where exactly does `graphify-out/` live in multi-repo mode?
4. **Scope of v1** — is the iframe graph + overview + query enough, or is per-item graph context (graph the diff of one card) wanted too?

---

## Recommendation

Build **Track B, Phases 0–2** first: a server-side, AST-default graph with a "Graph" dialog (overview + iframe + query). ~2.5 days, high confidence, near-zero token cost, reuses the binary we already maintain. Treat **Track A (agent plugin)** and **semantic rebuild** as opt-in follow-ups once the surface proves useful. Total to a polished v1 incl. optional phases: ~4–5 days.
