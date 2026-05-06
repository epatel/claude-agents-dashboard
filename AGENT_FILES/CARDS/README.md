# Cards

Living docs, one per domain. CLAUDE.md is a thin pointer; this folder is the canonical home.

| Card | Topic |
| --- | --- |
| [OVERVIEW](OVERVIEW.md) | Project intro + running |
| [CONVENTIONS](CONVENTIONS.md) | Canonical conventions (naming, organization, error handling, async, …) |
| [BACKEND_SERVICES](BACKEND_SERVICES.md) | 5 services behind `AgentOrchestrator` |
| [WEB_LAYER](WEB_LAYER.md) | `src/web/` (FastAPI app, routes, websocket) |
| [AGENT_RUNTIME](AGENT_RUNTIME.md) | `src/agent/` (Claude SDK, MCP tools, hooks) |
| [DOMAIN_AND_REPOSITORIES](DOMAIN_AND_REPOSITORIES.md) | `ItemState` FSM, repositories, `AgentConfig` |
| [FRONTEND](FRONTEND.md) | Vanilla JS, Jinja2, dialogs |
| [DATABASE](DATABASE.md) | SQLite, migrations, CLI |
| [TESTING](TESTING.md) | Test layout, suites, conventions |
| [OLLAMA_PROVIDER](OLLAMA_PROVIDER.md) | Models + experimental Ollama provider |
| [COMMIT_POLICY](COMMIT_POLICY.md) | Git commit conventions |
| [KEY_FLOWS](KEY_FLOWS.md) | Agent start, clarification, merge, WIP, multi-repo |
| [MCP_TOOLS](MCP_TOOLS.md) | Built-in MCP tools available to agents |
| [PROJECT_MAP](PROJECT_MAP.md) | Shorthand vocabulary for flows + UI elements |
| [PROJECT_MAP_STRATEGY](PROJECT_MAP_STRATEGY.md) | Strategy doc for the project map |
