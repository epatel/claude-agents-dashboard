# Built-in MCP Tools

Available to agents:

- `ask_user` — clarification dialog
- `create_todo` — create new item (with `requires` for dependencies)
- `set_commit_message`
- `request_command_access` — prompt user to allow a denied command
- `view_board`
- `request_tool_access` — prompt user to allow a denied built-in tool
- `create_shortcut`

**External MCP servers** get wildcard tool permissions (`mcp__{server_name}__*`).
