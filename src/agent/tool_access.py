"""MCP tool for agents to request access to built-in tools."""

from claude_agent_sdk import tool, create_sdk_mcp_server

REQUEST_TOOL_ACCESS_SCHEMA = {
    "type": "object",
    "properties": {
        "tool_name": {
            "type": "string",
            "description": "The built-in tool name to request access for (e.g., 'WebSearch', 'WebFetch').",
        },
        "reason": {
            "type": "string",
            "description": "Brief explanation of why you need this tool.",
        },
    },
    "required": ["tool_name", "reason"],
}


def create_tool_access_server(on_request_tool):
    """Create MCP server with request_tool_access tool.

    Args:
        on_request_tool: async callback(tool_name, reason) -> str
            Returns "approved" or "denied".
    """

    @tool(
        "request_tool_access",
        "Request permission to use a built-in tool that is currently disabled. "
        "The user will be prompted to approve or deny access. "
        "If approved, the tool will be enabled and you can use it.",
        REQUEST_TOOL_ACCESS_SCHEMA,
    )
    async def request_tool_access(input: dict) -> dict:
        tool_name = input.get("tool_name", "")
        reason = input.get("reason", "")
        response = await on_request_tool(tool_name, reason)
        return {"content": [{"type": "text", "text": response}]}

    return create_sdk_mcp_server("tool_access", tools=[request_tool_access])
