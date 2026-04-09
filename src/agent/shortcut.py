"""Shortcut creation tool for agents.

Creates an MCP server with a 'create_shortcut' tool that agents can call
to add quick-launch bash command shortcuts to the board's shortcut bar.
"""

from claude_agent_sdk import tool, create_sdk_mcp_server

CREATE_SHORTCUT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": (
                "A short, descriptive name for the shortcut (e.g., 'Run tests', "
                "'Build project', 'Lint code')."
            ),
        },
        "command": {
            "type": "string",
            "description": (
                "The bash command to run when the shortcut is activated "
                "(e.g., 'npm test', 'cargo build', 'python -m pytest')."
            ),
        },
    },
    "required": ["name", "command"],
}


def create_shortcut_server(on_create_shortcut):
    """Create an MCP server with the create_shortcut tool.

    Args:
        on_create_shortcut: async callback(name: str, command: str) -> dict
            Called when agent uses the create_shortcut tool.
            Should persist the shortcut and return the created shortcut dict.
    """

    @tool(
        "create_shortcut",
        "Create a quick-launch bash command shortcut on the board's shortcut bar. "
        "Use this to set up useful commands that the user can run with one click, "
        "such as test runners, build commands, linters, or dev servers.",
        CREATE_SHORTCUT_SCHEMA,
    )
    async def create_shortcut(input: dict) -> dict:
        """Create a shortcut on the board."""
        name = input.get("name", "")
        command = input.get("command", "")
        result = await on_create_shortcut(name, command)
        return {"content": [{"type": "text", "text": f"Shortcut created: {result.get('name', name)}"}]}

    return create_sdk_mcp_server("shortcut", tools=[create_shortcut])
