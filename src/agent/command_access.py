"""MCP tool for agents to request access to shell commands."""

from claude_agent_sdk import tool, create_sdk_mcp_server

REQUEST_COMMAND_ACCESS_SCHEMA = {
    "type": "object",
    "properties": {
        "command": {
            "type": "string",
            "description": "The command name to request access for (e.g., 'flutter', 'npm', 'cargo').",
        },
        "reason": {
            "type": "string",
            "description": "Brief explanation of why you need this command.",
        },
    },
    "required": ["command", "reason"],
}


def create_command_access_server(on_request_command):
    """Create MCP server with request_command_access tool.

    Args:
        on_request_command: async callback(command, reason) -> str
            Returns "approved" or "denied".
    """

    @tool(
        "request_command_access",
        "Request permission to run a shell command that is currently blocked. "
        "The user will be prompted to approve or deny access. "
        "If approved, the command will be added to the allowed list and you can retry.",
        REQUEST_COMMAND_ACCESS_SCHEMA,
    )
    async def request_command_access(input: dict) -> dict:
        command = input.get("command", "")
        reason = input.get("reason", "")
        response = await on_request_command(command, reason)
        return {"content": [{"type": "text", "text": response}]}

    return create_sdk_mcp_server("command_access", tools=[request_command_access])
