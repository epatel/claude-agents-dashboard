# Graphify Knowledge Graph

> **Load when**: querying the codebase knowledge graph, rebuilding it, or upgrading the graphify tool/skill.
> **Skip when**: doing normal feature work that doesn't touch `graphify-out/`.

A persistent knowledge graph of this repo lives in **`graphify-out/`** (`graph.html`, `graph.json`, `GRAPH_REPORT.md`, `cost.json`, `cache/`). Built by the `/graphify` skill from AST extraction (code) + LLM semantic extraction (docs/images).

## Critical: graphify lives in the venv, not on PATH

graphify is **not on PATH** — it's installed only in the project venv. Always invoke it explicitly:
```bash
venv/bin/graphify version             # prints the installed version (package name on PyPI is `graphifyy`)
venv/bin/python -m graphify version   # equivalent module form
```
Either form works. The dashboard's own `GraphService` always uses the **module form** with its own interpreter (`[sys.executable, "-m", "graphify", …]`, `src/services/graph_service.py:98-102`), so it never depends on the console script or on PATH.

## Using the graph (cheap, no LLM)

```bash
venv/bin/graphify query "How does WorkflowService start an agent?"   # BFS traversal (--budget N caps output)
venv/bin/graphify path "Database" "AgentOrchestrator"                # shortest path between nodes
venv/bin/graphify explain "DatabaseService"                          # plain-language node summary
venv/bin/graphify affected "DatabaseService"                         # reverse traversal: what breaks if X changes
venv/bin/graphify god-nodes                                          # most-connected nodes, live from the graph
```
Prefer these over reading source when answering architecture questions — the graph already maps cross-module relationships. God nodes (most-connected): `Database`, `DatabaseService`, `WorkflowService`, `Migration`, `SessionService`.

A bare symbol name often matches several nodes (the code definition plus every doc that mentions it). The CLI then lists the candidates and asks you to retry with `<path>::Symbol` or the full node id, e.g. `explain "src/services/database_service.py::DatabaseService"`.

## Rebuilding / maintaining

```bash
venv/bin/graphify update .         # incremental: re-extract only changed code files (no LLM, free)
/graphify .                        # full rebuild via skill (AST + LLM semantic; ~230k tokens)
venv/bin/graphify cluster-only .   # re-run clustering on existing graph only
```
- A full `/graphify .` rebuild costs LLM tokens (semantic extraction runs as Claude subagents unless `GEMINI_API_KEY`/`GOOGLE_API_KEY` is set). Run sparingly — prefer `update` after code changes.
- Cumulative token cost is tracked in `graphify-out/cost.json`.

**Upgrading the tool + skill** (do both together — the CLI prints a drift warning on every command until you do):
```bash
venv/bin/pip install --upgrade graphifyy     # update the package in the venv
venv/bin/graphify install --platform claude  # sync ~/.claude/skills/graphify/ to the new version
venv/bin/graphify version                    # confirm: no drift warning, both at the same version
```
`install` keeps the replaced skill as `~/.claude/skills/graphify/SKILL.md.bak`. The 0.9.91 CLI also refreshes the skill automatically on first run after an upgrade (`GRAPHIFY_NO_AUTO_REFRESH=1` disables it). Last upgraded 2026-10-16 to **0.9.91** (from 0.9.64).

Two notices the 0.9.x CLI may print after an `update`, both optional and neither free:
- *"pre-#1504 node-ID scheme"* — the graph predates path-qualified node ids, which is why same-name symbols collide (see the `::` note above). Fixed only by a full `graphify extract --force`, which runs semantic LLM extraction.
- *"community set changed since labeling"* — communities were renamed by their hub instead of by the LLM. `graphify label --missing-only` refreshes names and costs LLM tokens.

## The in-dashboard surface

Everything above is the CLI/skill workflow you drive by hand. The dashboard also owns the graph as a feature, and that is a different set of files:

- **`GraphService`** (`src/services/graph_service.py`) — build / refresh / query / status, version detection and cost tracking; shells out via `python -m graphify` and owns `graphify-out/`.
- **Config** — the `graphify_enabled`, `graphify_auto_refresh` and `graphify_backend` columns on `agent_config` (migration `028`), surfaced as **Settings ▸ Graphify**. Off by default.
- **Agent access** — the read-only `graph_query` MCP tool (`src/agent/graph_query.py`), wired into a session only when `graphify_enabled` **and** the provider profile allows it.
- **Routes** — `GET`/`POST` under `/api/graphify/*` in `src/web/routes.py`; progress reaches the UI as the `graph_build_progress` / `graph_ready` WebSocket events from `NotificationService`.
- **Auto-refresh** — `WorkflowService._maybe_refresh_graph_after_merge` re-runs an incremental update after a successful merge when `graphify_auto_refresh` is on.

AST builds/refreshes are free; semantic (LLM) builds cost tokens — see the rebuild notes above.

---

**See also**: [ARCHITECTURE](ARCHITECTURE.md) (the structure the graph maps), [PROJECT_MAP](PROJECT_MAP.md) (hand-curated flow vocabulary — complements the auto-extracted graph; `flow.graph` covers the build/query path), [DATABASE](DATABASE.md) (migration 028).
