"""Todo management tools for agents.

Creates an MCP server with 'create_todo' and 'delete_todo' tools that agents
can call to manage todo items on the board.
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
        "epic_id": {
            "type": "string",
            "description": "Optional epic ID to assign this todo to. Use view_board to see available epics.",
        },
    },
    "required": ["title"],
}

DELETE_TODO_SCHEMA = {
    "type": "object",
    "properties": {
        "item_id": {
            "type": "string",
            "description": "The ID of the todo item to delete. Use view_board to find item IDs.",
        },
    },
    "required": ["item_id"],
}


def create_todo_server(on_create_todo, on_delete_todo=None):
    """Create an MCP server with todo management tools.

    Args:
        on_create_todo: async callback(title, description, epic_id=None) -> dict
            Called when agent uses the create_todo tool.
            Should return the created item info (id, title, etc).
        on_delete_todo: async callback(item_id) -> str
            Called when agent uses the delete_todo tool.
            Should return a confirmation message.
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
        epic_id = input.get("epic_id")
        item_info = await on_create_todo(title, description, epic_id)
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Created todo item: {item_info['title']} (ID: {item_info['id']})"
                }
            ]
        }

    tools = [create_todo]

    if on_delete_todo:
        @tool(
            "delete_todo",
            "Delete a todo item from the board. Only items in the 'todo' column can be deleted. "
            "Use view_board first to see item IDs. Use this to remove completed planning items "
            "or reorganize the backlog by deleting and recreating items.",
            DELETE_TODO_SCHEMA,
        )
        async def delete_todo(input: dict) -> dict:
            """Delete a todo item."""
            item_id = input.get("item_id", "")
            result = await on_delete_todo(item_id)
            return {
                "content": [
                    {
                        "type": "text",
                        "text": result,
                    }
                ]
            }
        tools.append(delete_todo)

    return create_sdk_mcp_server("todo", tools=tools)
