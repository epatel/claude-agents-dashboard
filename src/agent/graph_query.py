"""Graph query tool for agents.

Creates an MCP server with a 'graph_query' tool so agents can ask
natural-language questions of the project's graphify knowledge graph
(read-only). Registered only when graphify is enabled in agent config.
"""

from claude_agent_sdk import tool, create_sdk_mcp_server

GRAPH_QUERY_SCHEMA = {
    "type": "object",
    "properties": {
        "question": {
            "type": "string",
            "description": (
                "A natural-language question about the codebase, e.g. "
                "'what calls approve_item?' or 'how does the agent start flow connect?'"
            ),
        },
    },
    "required": ["question"],
}


def create_graph_query_server(on_graph_query):
    """Create an MCP server with the graph_query tool.

    Args:
        on_graph_query: async callback(question: str) -> str
            Returns a graph-traversal answer for the question.
    """

    @tool(
        "graph_query",
        "Query the project's knowledge graph (code structure and relationships). "
        "Ask a natural-language question to orient before editing — e.g. what "
        "calls a function, where a concept lives, or how a flow connects. "
        "Read-only; answers cite source locations.",
        GRAPH_QUERY_SCHEMA,
    )
    async def graph_query(input: dict) -> dict:
        question = (input or {}).get("question", "")
        answer = await on_graph_query(question)
        return {"content": [{"type": "text", "text": answer}]}

    return create_sdk_mcp_server("graph_query", tools=[graph_query])
