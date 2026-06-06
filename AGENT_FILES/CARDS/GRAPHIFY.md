# Graphify Knowledge Graph

> **Load when**: querying the codebase knowledge graph, rebuilding it, or upgrading the graphify tool/skill.
> **Skip when**: doing normal feature work that doesn't touch `graphify-out/`.

A persistent knowledge graph of this repo lives in **`graphify-out/`** (`graph.html`, `graph.json`, `GRAPH_REPORT.md`, `cost.json`, `cache/`). Built by the `/graphify` skill from AST extraction (code) + LLM semantic extraction (docs/images).

## Critical: graphify lives in the venv, not on PATH

graphify is **not on PATH** — it's installed only in the project venv. Always invoke it explicitly:
```bash
venv/bin/graphify version          # → graphify 0.8.33 (package name on PyPI is `graphifyy`)
```
The pipeline pins its interpreter in `graphify-out/.graphify_python`; every step runs `$(cat graphify-out/.graphify_python)`. If that file is stale/missing, repoint it: `venv/bin/python -c "import sys; open('graphify-out/.graphify_python','w').write(sys.executable)"`.

## Using the graph (cheap, no LLM)

```bash
venv/bin/graphify query "How does WorkflowService start an agent?"   # BFS traversal
venv/bin/graphify path "Database" "AgentOrchestrator"                # shortest path between nodes
venv/bin/graphify explain "DatabaseService"                          # plain-language node summary
```
Prefer these over reading source when answering architecture questions — the graph already maps cross-module relationships. God nodes (most-connected): `Database`, `DatabaseService`, `WorkflowService`, `Migration`, `SessionService`.

## Rebuilding / maintaining

```bash
venv/bin/graphify update .         # incremental: re-extract only changed code files (no LLM, free)
/graphify .                        # full rebuild via skill (AST + LLM semantic; ~230k tokens)
venv/bin/graphify cluster-only .   # re-run clustering on existing graph only
```
- A full `/graphify .` rebuild costs LLM tokens (semantic extraction runs as Claude subagents unless `GEMINI_API_KEY`/`GOOGLE_API_KEY` is set). Run sparingly — prefer `update` after code changes.
- Cumulative token cost is tracked in `graphify-out/cost.json`.

**Upgrading the tool + skill** (do both together — the CLI warns when they drift):
```bash
venv/bin/pip install --upgrade graphifyy     # update the package in the venv
venv/bin/graphify install --platform claude  # sync ~/.claude/skills/graphify/ to the new version
```

---

**See also**: [ARCHITECTURE](ARCHITECTURE.md) (the structure the graph maps), [PROJECT_MAP](PROJECT_MAP.md) (hand-curated flow vocabulary — complements the auto-extracted graph).
