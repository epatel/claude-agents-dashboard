# CLAUDE.md

Standalone scrum board that orchestrates Claude agents working on a **separate target project** (or a workspace of sibling git repos in multi-repo mode). Server code lives here; data directory (`agents-lab/`) is created in the target project / workspace root.

Project documentation has been split into per-domain cards. See **[`AGENT_FILES/CARDS/`](AGENT_FILES/CARDS/README.md)** for the index.

## Quick start

```bash
./run.sh /path/to/target-project    # Single-repo mode
./run.sh /path/to/workspace-folder  # Multi-repo mode
./run-tests.sh                      # All tests
```

## Card index

| Card | Topic |
| --- | --- |
| [OVERVIEW](AGENT_FILES/CARDS/OVERVIEW.md) | Project intro + running |
| [CONVENTIONS](AGENT_FILES/CARDS/CONVENTIONS.md) | Canonical conventions (naming, organization, error handling, async, …) |
| [BACKEND_SERVICES](AGENT_FILES/CARDS/BACKEND_SERVICES.md) | 5 services behind `AgentOrchestrator` |
| [WEB_LAYER](AGENT_FILES/CARDS/WEB_LAYER.md) | `src/web/` (FastAPI app, routes, websocket) |
| [AGENT_RUNTIME](AGENT_FILES/CARDS/AGENT_RUNTIME.md) | `src/agent/` (Claude SDK, MCP tools, hooks) |
| [DOMAIN_AND_REPOSITORIES](AGENT_FILES/CARDS/DOMAIN_AND_REPOSITORIES.md) | `ItemState` FSM, repositories, `AgentConfig` |
| [FRONTEND](AGENT_FILES/CARDS/FRONTEND.md) | Vanilla JS + Jinja2 + dialogs |
| [DATABASE](AGENT_FILES/CARDS/DATABASE.md) | SQLite, migrations, CLI |
| [TESTING](AGENT_FILES/CARDS/TESTING.md) | Test layout, suites, conventions |
| [OLLAMA_PROVIDER](AGENT_FILES/CARDS/OLLAMA_PROVIDER.md) | Models + experimental Ollama provider |
| [COMMIT_POLICY](AGENT_FILES/CARDS/COMMIT_POLICY.md) | Git commit conventions |
| [KEY_FLOWS](AGENT_FILES/CARDS/KEY_FLOWS.md) | Agent start, clarification, merge, WIP, multi-repo |
| [MCP_TOOLS](AGENT_FILES/CARDS/MCP_TOOLS.md) | Built-in MCP tools available to agents |
| [PROJECT_MAP](AGENT_FILES/CARDS/PROJECT_MAP.md) | Shorthand vocabulary for flows + UI elements |
| [PROJECT_MAP_STRATEGY](AGENT_FILES/CARDS/PROJECT_MAP_STRATEGY.md) | Strategy doc for the project map |

**Naming reference**: [`AGENT_FILES/CARDS/PROJECT_MAP.md`](AGENT_FILES/CARDS/PROJECT_MAP.md) defines a shared shorthand vocabulary (`flow.agent-start`, `flow.merge`, `flow.command-gate`, …).
