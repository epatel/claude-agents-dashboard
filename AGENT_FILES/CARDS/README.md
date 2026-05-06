# Cards — routing manifest

Living docs grouped by **when to load**. Scan this index first, then load only the cards whose **Load when** matches the task. Don't bulk-load.

Each card also carries its own `> Load when` block so you can verify relevance after landing on it.

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
