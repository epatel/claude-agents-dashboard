"""PreToolUse hook that filters bash commands against an allowed list."""


def make_command_filter_hook(allowed_commands: list[str], session=None):
    """Create a PreToolUse hook callback that allows only listed commands.

    Args:
        allowed_commands: List of command prefixes (e.g., ["flutter", "npm"]).
            The first word of each bash command is checked against this list.
        session: Optional AgentSession reference to capture session_id from hook input.
    """

    async def hook(hook_input, tool_use_id, context):
        # Capture session_id from hook input for mid-session restart
        if session is not None and hasattr(hook_input, 'get'):
            sid = hook_input.get("session_id")
            if sid:
                session.current_session_id = sid

        tool_name = hook_input.get("tool_name", "")
        if tool_name != "Bash":
            return {}

        command = hook_input.get("tool_input", {}).get("command", "").strip()
        first_word = command.split()[0] if command else ""

        for allowed in allowed_commands:
            if first_word == allowed:
                return {}

        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"Command '{first_word}' is not in the allowed commands list. "
                    "Use the mcp__command_access__request_command_access tool to ask the user for permission."
                ),
            }
        }

    return hook
