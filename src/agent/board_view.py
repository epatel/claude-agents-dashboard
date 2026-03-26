"""Board view tool for agents.

Creates an MCP server with a 'view_board' tool that agents can call
to see all items on the board grouped by column (todo, doing, review, done).
"""

from claude_agent_sdk import tool, create_sdk_mcp_server

VIEW_BOARD_SCHEMA = {
    "type": "object",
    "properties": {},
}


def create_board_view_server(on_view_board):
    """Create an MCP server with the view_board tool.

    Args:
        on_view_board: async callback() -> str
            Returns a formatted string of all board items grouped by column.
    """

    @tool(
        "view_board",
        "View all items on the project board. "
        "Shows items grouped by column: Todo, Doing, Review, and Done. "
        "Use this to understand what work is planned, in progress, or completed.",
        VIEW_BOARD_SCHEMA,
    )
    async def view_board(input: dict) -> dict:
        """View the board."""
        board_text = await on_view_board()
        return {
            "content": [
                {
                    "type": "text",
                    "text": board_text,
                }
            ]
        }

    return create_sdk_mcp_server("board_view", tools=[view_board])
