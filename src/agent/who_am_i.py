"""Who-am-I tool for agents.

Creates an MCP server with a 'who_am_i' tool that an agent can call to get
its OWN board item — the card it is currently working on. Unlike view_board
(which lists every card with no marker for the caller), this returns just the
agent's own item, including the item ID it needs when wiring up dependencies
(the `requires` field of create_todo).
"""

from claude_agent_sdk import tool, create_sdk_mcp_server

WHO_AM_I_SCHEMA = {
    "type": "object",
    "properties": {},
}


def create_who_am_i_server(on_who_am_i):
    """Create an MCP server with the who_am_i tool.

    Args:
        on_who_am_i: async callback() -> dict
            Returns the agent's own item dict (id, title, description,
            column_name, status, epic_id, auto_start, auto_approve,
            dependencies). May return {"error": "..."} if unavailable.
    """

    @tool(
        "who_am_i",
        "Get YOUR own board item — the card you are currently working on. "
        "Returns your item ID, title, description, current column, status, and "
        "dependencies. Use the returned item ID whenever a follow-up task must "
        "depend on you, i.e. as an entry in the `requires` field of create_todo.",
        WHO_AM_I_SCHEMA,
    )
    async def who_am_i(input: dict) -> dict:
        """Return this agent's own board item."""
        item = await on_who_am_i()
        if not item or item.get("error"):
            msg = item.get("error") if item else "Could not determine your board item."
            return {"content": [{"type": "text", "text": msg}]}

        deps = item.get("dependencies") or []
        dep_text = ", ".join(d.get("id", "") for d in deps) if deps else "(none)"
        lines = [
            f"You are board item: {item.get('id', '')}",
            f"Title: {item.get('title', '')}",
            f"Column: {item.get('column_name', '')}",
        ]
        if item.get("status"):
            lines.append(f"Status: {item['status']}")
        if item.get("epic_id"):
            lines.append(f"Epic: {item['epic_id']}")
        lines.append(f"Depends on (requires): {dep_text}")
        if item.get("description"):
            lines.append(f"\nDescription:\n{item['description']}")
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    return create_sdk_mcp_server("who_am_i", tools=[who_am_i])
