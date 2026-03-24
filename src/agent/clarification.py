"""Clarification tool for agents.

Creates an MCP server with an 'ask_user' tool that agents can call
when they need user input. The orchestrator intercepts the tool call,
moves the item to Clarify, and waits for the user's response.
"""

from typing import TypedDict
from claude_agent_sdk import tool, create_sdk_mcp_server


class AskUserInput(TypedDict, total=False):
    question: str
    choices: list[str]


def create_clarification_server(on_clarify):
    """Create an MCP server with the ask_user tool.

    Args:
        on_clarify: async callback(prompt, choices) -> str
            Called when agent uses the ask_user tool.
            Should return the user's response (blocks until answered).
    """

    @tool(
        "ask_user",
        "Ask the user a question when you need clarification, guidance, or a decision. "
        "Use this whenever you are unsure how to proceed, need to choose between approaches, "
        "or need information that isn't available in the codebase. "
        "Provide a clear question and optionally a list of choices.",
        AskUserInput,
    )
    async def ask_user(input: AskUserInput) -> dict:
        """Ask the user for clarification."""
        question = input.get("question", "")
        choices = input.get("choices")
        response = await on_clarify(question, choices)
        return {"content": [{"type": "text", "text": response}]}

    return create_sdk_mcp_server("clarification", tools=[ask_user])
