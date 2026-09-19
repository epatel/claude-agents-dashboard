# Graphify Knowledge Graph

> **Load when**: querying the codebase knowledge graph, rebuilding it, or upgrading the graphify tool/skill.
> **Skip when**: doing normal feature work that doesn't touch `graphify-out/`.

A persistent knowledge graph of this repo lives in **`graphify-out/`** (`graph.html`, `graph.json`, `GRAPH_REPORT.md`, `cost.json`, `cache/`). Built by the `/graphify` skill from AST extraction (code) + LLM semantic extraction (docs/images).

## Critical: graphify lives in the venv, not on PATH

graphify is **not on PATH** — it's installed only in the project venv. Always invoke it explicitly:
```bash
venv/bin/graphify version          # prints the installed version (package name on PyPI is `graphifyy`)
```
The pipeline pins its interpreter in `graphify-out/.graphify_python`; every step runs `$(cat graphify-out/.graphify_python)`. If that file is stale/missing, repoint it: `venv/bin/python -c "import sys; open('graphify-out/.graphify_python','w').write(sys.executable)"`.

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
`install` keeps the replaced skill as `~/.claude/skills/graphify/SKILL.md.bak`. Last upgraded 2026-09-19 to **0.9.64** (from 0.8.44 / skill 0.8.33).

Two notices the 0.9.x CLI may print after an `update`, both optional and neither free:
- *"pre-#1504 node-ID scheme"* — the graph predates path-qualified node ids, which is why same-name symbols collide (see the `::` note above). Fixed only by a full `graphify extract --force`, which runs semantic LLM extraction.
- *"community set changed since labeling"* — communities were renamed by their hub instead of by the LLM. `graphify label --missing-only` refreshes names and costs LLM tokens.

---

**See also**: [ARCHITECTURE](ARCHITECTURE.md) (the structure the graph maps), [PROJECT_MAP](PROJECT_MAP.md) (hand-curated flow vocabulary — complements the auto-extracted graph).
