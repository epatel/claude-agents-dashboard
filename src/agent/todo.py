"""Todo and epic management tools for agents.

Creates an MCP server with 'create_todo', 'delete_todo', and 'create_epic'
tools that agents can call to manage todo items and epics on the board.
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
        "requires": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional list of item IDs that this todo depends on (must be completed before this one can start). Use view_board to see available item IDs.",
        },
    },
    "required": ["title"],
}

CREATE_EPIC_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "The title of the epic. Should describe a higher-level work stream or feature area.",
        },
        "color": {
            "type": "string",
            "description": "Color for the epic. One of: red, orange, amber, green, teal, blue, purple, pink. Defaults to blue.",
            "enum": ["red", "orange", "amber", "green", "teal", "blue", "purple", "pink"],
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


def create_todo_server(on_create_todo, on_delete_todo=None, on_create_epic=None):
    """Create an MCP server with todo and epic management tools.

    Args:
        on_create_todo: async callback(title, description, epic_id=None, requires=None) -> dict
            Called when agent uses the create_todo tool.
            Should return the created item info (id, title, etc).
        on_delete_todo: async callback(item_id) -> str
            Called when agent uses the delete_todo tool.
            Should return a confirmation message.
        on_create_epic: async callback(title, color) -> dict
            Called when agent uses the create_epic tool.
            Should return the created epic info (id, title, color).
    """

    @tool(
        "create_todo",
        "Create a new todo item when you identify tasks that need to be done. "
        "Use this to break down work into smaller actionable items, "
        "create follow-up tasks, or note issues that need attention. "
        "Provide a clear title and optionally a detailed description. "
        "IMPORTANT: If this todo depends on other todos being completed first, "
        "pass their item IDs in the 'requires' array — this enforces the dependency "
        "so agents cannot start this task until prerequisites are done.",
        CREATE_TODO_SCHEMA,
    )
    async def create_todo(input: dict) -> dict:
        """Create a new todo item."""
        title = input.get("title", "")
        description = input.get("description", "")
        epic_id = input.get("epic_id")
        requires = input.get("requires")
        item_info = await on_create_todo(title, description, epic_id, requires)
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

    if on_create_epic:
        @tool(
            "create_epic",
            "Create a new epic to group related todo items into a higher-level work stream. "
            "Use this when you identify a set of related tasks that belong together. "
            "Provide a descriptive title and optionally a color.",
            CREATE_EPIC_SCHEMA,
        )
        async def create_epic(input: dict) -> dict:
            """Create a new epic."""
            title = input.get("title", "")
            color = input.get("color", "blue")
            epic_info = await on_create_epic(title, color)
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Created epic: {epic_info['title']} (ID: {epic_info['id']}, color: {epic_info['color']})"
                    }
                ]
            }
        tools.append(create_epic)

    return create_sdk_mcp_server("todo", tools=tools)
