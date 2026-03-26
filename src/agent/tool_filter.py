"""PreToolUse hook that filters built-in tools against an enabled list."""

from ..constants import OPTIONAL_BUILTIN_TOOLS

# Set of tool names that require opt-in
OPTIONAL_TOOL_NAMES = {t["name"] for t in OPTIONAL_BUILTIN_TOOLS}


def make_tool_filter_hook(allowed_builtin_tools: list[str]):
    """Create a PreToolUse hook callback that blocks disabled built-in tools.

    Args:
        allowed_builtin_tools: List of enabled tool names (e.g., ["WebSearch"]).
    """

    async def hook(hook_input, tool_use_id, context):
        tool_name = hook_input.get("tool_name", "")

        # Only filter optional built-in tools
        if tool_name not in OPTIONAL_TOOL_NAMES:
            return {}

        # Allow if enabled
        if tool_name in allowed_builtin_tools:
            return {}

        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"Tool '{tool_name}' is not enabled. "
                    "Use the mcp__tool_access__request_tool_access tool to ask the user for permission."
                ),
            }
        }

    return hook
