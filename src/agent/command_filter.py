"""PreToolUse hook that filters bash commands against an allowed list."""

import shlex

# Shell metacharacters that can chain or redirect commands
SHELL_OPERATORS = [";", "&&", "||", "|", ">>", ">", "<", "$(", "`"]


def _contains_shell_operators(command: str) -> str | None:
    """Check if a command contains shell operators that could bypass filtering.

    Returns the matched operator string, or None if clean.
    """
    for op in SHELL_OPERATORS:
        if op in command:
            return op
    return None


def _extract_command_name(command: str) -> str:
    """Extract the first command word using shlex for robust parsing.

    Falls back to simple split if shlex fails (e.g., on unmatched quotes).
    """
    try:
        tokens = shlex.split(command)
        return tokens[0] if tokens else ""
    except ValueError:
        # shlex.split fails on malformed input (unmatched quotes, etc.)
        # Deny by returning empty string which won't match any allowed command
        return ""


def make_command_filter_hook(allowed_commands: list[str], session=None):
    """Create a PreToolUse hook callback that allows only listed commands.

    Args:
        allowed_commands: List of command prefixes (e.g., ["flutter", "npm"]).
            The first word of each bash command is checked against this list.
            Commands containing shell operators (;, &&, ||, |, etc.) are
            rejected outright to prevent filter bypass.
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

        # Reject commands with shell operators that could chain malicious commands
        shell_op = _contains_shell_operators(command)
        if shell_op is not None:
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"Command contains shell operator '{shell_op}' which is not allowed. "
                        "Each command must be run separately without chaining. "
                        "Use the mcp__command_access__request_command_access tool to ask the user for permission."
                    ),
                }
            }

        first_word = _extract_command_name(command)

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
