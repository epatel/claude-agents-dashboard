# Cards

CLAUDE.md broken into per-domain cards.

- [OVERVIEW](OVERVIEW.md) — what the project is + how to run it
- [BACKEND_SERVICES](BACKEND_SERVICES.md) — the 5 services behind `AgentOrchestrator`
- [WEB_LAYER](WEB_LAYER.md) — `src/web/` (FastAPI app, routes, websocket)
- [AGENT_RUNTIME](AGENT_RUNTIME.md) — `src/agent/` (Claude SDK, MCP tools, hooks)
- [DOMAIN_AND_REPOSITORIES](DOMAIN_AND_REPOSITORIES.md) — `ItemState` FSM, repositories, `AgentConfig`
- [FRONTEND](FRONTEND.md) — vanilla JS, Jinja2, dialogs
- [DATABASE](DATABASE.md) — SQLite, migrations, CLI
- [MODELS](MODELS.md) — selectable Claude models + Ollama
- [TESTS](TESTS.md) — test layout (unit / integration / smoke / e2e)
- [KEY_FLOWS](KEY_FLOWS.md) — agent start, clarification, merge, pause/resume, WIP, multi-repo
- [MCP_TOOLS](MCP_TOOLS.md) — built-in MCP tools available to agents
- [PATTERNS](PATTERNS.md) — important coding patterns and gotchas
- [DEV_WORKFLOWS](DEV_WORKFLOWS.md) — adding features + debugging
