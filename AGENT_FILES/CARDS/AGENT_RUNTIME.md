# Agent Runtime

**Agent runtime** (`src/agent/`): the Claude SDK integration plus built-in MCP tool servers and PreToolUse hooks. One file per concern.

**MCP tools**:
- `clarification.py` — `ask_user`
- `todo.py` — `create_todo` / `create_epic` / `delete_todo`
- `board_view.py`
- `commit_message.py`
- `command_access.py`
- `tool_access.py`
- `shortcut.py`

**PreToolUse hooks**:
- `command_filter.py`
- `tool_filter.py`
- `path_guard.py`

**Plus**:
- `session.py` — system prompt + tool wiring
- `orchestrator.py` — the public facade
