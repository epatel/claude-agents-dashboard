"""Commit message tool for agents.

Creates an MCP server with a 'set_commit_message' tool that agents call
when they finish their work. The orchestrator stores the message and uses
it when committing and merging the agent's branch.
"""

from claude_agent_sdk import tool, create_sdk_mcp_server

SET_COMMIT_MESSAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "message": {
            "type": "string",
            "description": (
                "A concise git commit message summarizing the work done. "
                "Use conventional style: start with a verb like Add, Fix, Update, "
                "Refactor, Remove, etc. One line, no period at the end."
            ),
        },
    },
    "required": ["message"],
}


def create_commit_message_server(on_set_commit_message):
    """Create an MCP server with the set_commit_message tool.

    Args:
        on_set_commit_message: async callback(message: str) -> str
            Called when agent uses the set_commit_message tool.
            Should store the message and return confirmation.
    """

    @tool(
        "set_commit_message",
        "Set the git commit message for your work. Call this once when you have "
        "completed the task, right before your final response. The message should "
        "concisely describe what was done (not the task description). "
        "Use conventional commit style: start with a verb like Add, Fix, Update, "
        "Refactor, Remove, etc.",
        SET_COMMIT_MESSAGE_SCHEMA,
    )
    async def set_commit_message(input: dict) -> dict:
        """Set the commit message for the agent's work."""
        message = input.get("message", "")
        result = await on_set_commit_message(message)
        return {"content": [{"type": "text", "text": result}]}

    return create_sdk_mcp_server("commit_message", tools=[set_commit_message])
