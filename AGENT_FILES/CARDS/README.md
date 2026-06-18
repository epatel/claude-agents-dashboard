# Cards — routing manifest

Living docs grouped by **when to load**. Scan this index first, then load only the cards whose **Load when** matches the task. Don't bulk-load.

Each card also carries its own `> Load when` block so you can verify relevance after landing on it, and a `See also` footer pointing at sibling cards likely co-needed.

---

## Task → cards

Common operations and the cards that cover them. Order is suggested reading order.

| Task | Cards |
| --- | --- |
| Add a new MCP tool or PreToolUse hook | [ARCHITECTURE](ARCHITECTURE.md) (agent runtime) → [CONVENTIONS](CONVENTIONS.md) |
| Add a DB migration / new column | [DATABASE](DATABASE.md) → [CONVENTIONS](CONVENTIONS.md) (data layer) → [TESTING](TESTING.md) (`tests/unit/migrations/`) |
| Add a frontend dialog or card change | [ARCHITECTURE](ARCHITECTURE.md) (frontend) → [CONVENTIONS](CONVENTIONS.md) (frontend) |
| Add a new service / repository / endpoint | [ARCHITECTURE](ARCHITECTURE.md) → [CONVENTIONS](CONVENTIONS.md) |
| Trace an existing flow end-to-end | [PROJECT_MAP](PROJECT_MAP.md) only |
| Introduce a new named flow / UI vocabulary | [PROJECT_MAP_STRATEGY](PROJECT_MAP_STRATEGY.md) → [PROJECT_MAP](PROJECT_MAP.md) |
| Modify Ollama integration / model selection | [OLLAMA_PROVIDER](OLLAMA_PROVIDER.md) → [ARCHITECTURE](ARCHITECTURE.md) (`SessionService`) |
| Query / rebuild / upgrade the knowledge graph | [GRAPHIFY](GRAPHIFY.md) only |
| Work on the skills library / how skills reach agents | [SKILLS](SKILLS.md) → [ARCHITECTURE](ARCHITECTURE.md) (`SessionService`) |
| Localized bug fix in existing code | None — read the code |
| Demo the dashboard end-to-end / reproduce the kanban-demo run | [DEMO](DEMO.md) only |
| About to commit | [COMMIT_POLICY](COMMIT_POLICY.md) |

If your task isn't above, fall through to the **Load when** triggers below.

---

## Orientation

### [ARCHITECTURE](ARCHITECTURE.md)
- **Load when**: first orienting on this codebase, or you need to know which file/service owns a concept.
- **Skip when**: you already know the layout.
- *Tour of backend services, web layer, agent runtime, domain/repositories, frontend, built-in MCP tools.*

### [CONVENTIONS](CONVENTIONS.md)
- **Load when**: writing or reviewing non-trivial code in `src/`.
- **Skip when**: doc-only edits or single-line fixes.
- *Naming, file organization, module boundaries, error handling, async, data layer, frontend, comments, simplicity bias.*

---

## Workflows

### [DATABASE](DATABASE.md)
- **Load when**: writing or running a DB migration; whitelisting a new column.
- **Skip when**: not touching SQL or migrations.
- *Migration CLI, whitelist requirements, inspection commands.*

### [TESTING](TESTING.md)
- **Load when**: adding or modifying tests; deciding which suite to put a new test in.
- **Skip when**: writing production code with no test changes.
- *Test layout (unit / integration / smoke / e2e), suite conventions.*

### [COMMIT_POLICY](COMMIT_POLICY.md)
- **Load when**: about to run `git commit`, or changes touch annotated images / merge artifacts.
- **Skip when**: not committing.
- *Git commit conventions; what not to commit.*

---

## Reference

### [PROJECT_MAP](PROJECT_MAP.md)
- **Load when**: the user uses a `flow.*` / `card.*` / `dialog.*` shorthand; tracing a flow end-to-end with line numbers.
- **Skip when**: greenfield work not touching named flows.
- *Hand-curated flow vocabulary; UI element names; entry-point line numbers.*

### [PROJECT_MAP_STRATEGY](PROJECT_MAP_STRATEGY.md)
- **Load when**: extending the project-map vocabulary or designing a new flow name.
- **Skip when**: just consuming existing names.
- *Strategy / roadmap doc for the project-map system.*

### [OLLAMA_PROVIDER](OLLAMA_PROVIDER.md)
- **Load when**: working on Ollama integration, model selection, or the `--experimental` flag.
- **Skip when**: changes don't touch model providers.
- *Ollama setup; how the SDK routes requests when `ollama_enabled`.*

### [GRAPHIFY](GRAPHIFY.md)
- **Load when**: querying the `graphify-out/` knowledge graph, rebuilding it, or upgrading the graphify tool/skill.
- **Skip when**: normal feature work not touching the graph.
- *Use the venv binary (not PATH); query/path/explain; incremental update vs full rebuild; upgrading tool + skill together.*

### [SKILLS](SKILLS.md)
- **Load when**: working on the Agent-Skills library (install/browse/discover/enable), the Settings ▸ Skills tab, or how enabled skills reach agents.
- **Skip when**: feature work that doesn't touch skills.
- *`SkillsService`, gitignored `skill-library/`, per-project `enabled_skills`, delivery via SDK `plugins=`, `/api/skills/*`.*

### [DEMO](DEMO.md)
- **Load when**: explaining how to demo the dashboard end-to-end, or reproducing/updating the `kanban-demo` run.
- **Skip when**: normal feature work that doesn't touch the demo flow.
- *One-prompt `kanban-demo` walkthrough → "Doodle Together"; task-breakdown + dependency + auto-start showcase; live reference output.*
