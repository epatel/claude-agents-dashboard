"""Todo creation tool for agents.

Creates an MCP server with a 'create_todo' tool that agents can call
when they need to create new todo items. The orchestrator intercepts
the tool call and creates the new item in the database.
"""

from claude_agent_sdk import tool, create_sdk_mcp_server

CREATE_TODO_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "The title of the todo item. Should be clear and concise.",
        },
        "description": {
            "type": "string",
            "description": "Optional detailed description of the todo item.",
        },
    },
    "required": ["title"],
}


def create_todo_server(on_create_todo):
    """Create an MCP server with the create_todo tool.

    Args:
        on_create_todo: async callback(title, description) -> dict
            Called when agent uses the create_todo tool.
            Should return the created item info (id, title, etc).
    """

    @tool(
        "create_todo",
        "Create a new todo item when you identify tasks that need to be done. "
        "Use this to break down work into smaller actionable items, "
        "create follow-up tasks, or note issues that need attention. "
        "Provide a clear title and optionally a detailed description.",
        CREATE_TODO_SCHEMA,
    )
    async def create_todo(input: dict) -> dict:
        """Create a new todo item."""
        title = input.get("title", "")
        description = input.get("description", "")
        item_info = await on_create_todo(title, description)
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Created todo item: {item_info['title']} (ID: {item_info['id']})"
                }
            ]
        }

    return create_sdk_mcp_server("todo", tools=[create_todo])