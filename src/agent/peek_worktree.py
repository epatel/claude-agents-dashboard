"""Peek-worktree tool for agents.

Creates an MCP server with a 'peek_worktree' tool that lets an agent look at
what the OTHER agents on the board are changing, before their work is merged.

Each agent works in its own git worktree and the path_guard hook denies reads
outside it, so without this tool an agent is blind to in-flight work by its
peers — it discovers the collision at merge time, as a conflict. The tool is
read-only: the dashboard runs the git commands, the agent only gets text back.
"""

from claude_agent_sdk import tool, create_sdk_mcp_server

PEEK_WORKTREE_SCHEMA = {
    "type": "object",
    "properties": {
        "item_id": {
            "type": "string",
            "description": (
                "Board item ID of the agent whose worktree you want to inspect. "
                "Omit to get a summary of every active worktree, with the files "
                "that overlap your own changes flagged."
            ),
        },
        "path": {
            "type": "string",
            "description": (
                "Repo-relative file path. With item_id, returns that agent's "
                "actual diff for this one file instead of the file list."
            ),
        },
    },
}


def create_peek_worktree_server(on_peek_worktree):
    """Create an MCP server with the peek_worktree tool.

    Args:
        on_peek_worktree: async callback(item_id: str | None, path: str | None) -> str
            Returns formatted text describing other agents' in-flight changes.
    """

    @tool(
        "peek_worktree",
        "See what OTHER agents are currently changing in their worktrees, before "
        "their work is merged. Call it with no arguments for a summary of every "
        "active worktree — which files each agent has touched, with the ones that "
        "collide with your own changes flagged. Pass item_id for one agent's full "
        "file list, and item_id + path for that agent's diff of a single file. "
        "Use it before editing a shared file so you can align with in-flight work "
        "instead of colliding with it at merge time.",
        PEEK_WORKTREE_SCHEMA,
    )
    async def peek_worktree(input: dict) -> dict:
        """Report other agents' in-flight worktree changes."""
        args = input or {}
        text = await on_peek_worktree(
            args.get("item_id") or None,
            args.get("path") or None,
        )
        return {"content": [{"type": "text", "text": text}]}

    return create_sdk_mcp_server("peek_worktree", tools=[peek_worktree])
