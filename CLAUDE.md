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
| [BACKEND_SERVICES](AGENT_FILES/CARDS/BACKEND_SERVICES.md) | 5 services behind `AgentOrchestrator` |
| [WEB_LAYER](AGENT_FILES/CARDS/WEB_LAYER.md) | `src/web/` (FastAPI app, routes, websocket) |
| [AGENT_RUNTIME](AGENT_FILES/CARDS/AGENT_RUNTIME.md) | `src/agent/` (Claude SDK, MCP tools, hooks) |
| [DOMAIN_AND_REPOSITORIES](AGENT_FILES/CARDS/DOMAIN_AND_REPOSITORIES.md) | `ItemState` FSM, repositories, `AgentConfig` |
| [FRONTEND](AGENT_FILES/CARDS/FRONTEND.md) | Vanilla JS + Jinja2 + dialogs |
| [DATABASE](AGENT_FILES/CARDS/DATABASE.md) | SQLite, migrations, CLI |
| [MODELS](AGENT_FILES/CARDS/MODELS.md) | Selectable Claude models + Ollama |
| [TESTS](AGENT_FILES/CARDS/TESTS.md) | Test layout (unit / integration / smoke / e2e) |
| [KEY_FLOWS](AGENT_FILES/CARDS/KEY_FLOWS.md) | Agent start, clarification, merge, WIP, multi-repo |
| [MCP_TOOLS](AGENT_FILES/CARDS/MCP_TOOLS.md) | Built-in MCP tools available to agents |
| [PATTERNS](AGENT_FILES/CARDS/PATTERNS.md) | Coding patterns and gotchas |
| [DEV_WORKFLOWS](AGENT_FILES/CARDS/DEV_WORKFLOWS.md) | Adding features + debugging |

**Naming reference**: `AGENT_FILES/PROJECT_MAP.md` defines a shared shorthand vocabulary (`flow.agent-start`, `flow.merge`, `flow.command-gate`, …).
