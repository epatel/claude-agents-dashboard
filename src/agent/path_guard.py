"""PreToolUse hook that prevents agents from editing files in the main repo.

Agents run in git worktrees but can discover the main repo path from .git
metadata, CLAUDE.md references, or other sources. This hook blocks file
operations (Read, Edit, Write, Glob, Grep) that target the main project
directory instead of the agent's worktree.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Tools that accept a file_path parameter
FILE_PATH_TOOLS = {"Read", "Edit", "Write"}
# Tools that accept a path parameter
PATH_TOOLS = {"Glob", "Grep"}


def make_path_guard_hook(worktree_path: Path):
    """Create a PreToolUse hook that blocks file operations outside the worktree.

    The hook computes the target project root from the worktree path
    (agents-lab/worktrees/agent-{id} -> project root) and blocks any
    file operation that resolves to the project root but NOT the worktree.

    Args:
        worktree_path: Absolute path to the agent's worktree directory.
    """
    worktree_str = str(worktree_path.resolve())
    # Derive target project root: worktree is at {project}/agents-lab/worktrees/agent-{id}
    project_root = worktree_path.resolve().parent.parent.parent
    project_root_str = str(project_root)

    def _is_outside_worktree(path_str: str) -> bool:
        """Check if a path is inside the main project but outside the worktree."""
        if not path_str:
            return False
        try:
            resolved = str(Path(path_str).resolve())
        except (ValueError, OSError):
            return False

        # Only guard paths that fall within the project root
        if not resolved.startswith(project_root_str + "/") and resolved != project_root_str:
            return False

        # Allow if it's within the worktree
        if resolved.startswith(worktree_str + "/") or resolved == worktree_str:
            return False

        # It's in the project root but NOT in the worktree — block it
        return True

    deny_reason = (
        "This path is in the main project checkout, not your worktree. "
        f"Your worktree is at {worktree_str}. "
        "Use paths relative to your working directory or absolute paths within your worktree. "
        "For example, use './src/foo.py' or '{worktree}/src/foo.py' instead."
    )

    async def hook(hook_input, tool_use_id, context):
        tool_name = hook_input.get("tool_name", "")
        tool_input = hook_input.get("tool_input", {})

        # Check file_path tools (Read, Edit, Write)
        if tool_name in FILE_PATH_TOOLS:
            file_path = tool_input.get("file_path", "")
            if _is_outside_worktree(file_path):
                logger.warning(
                    f"Path guard blocked {tool_name} on {file_path} "
                    f"(outside worktree {worktree_str})"
                )
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": deny_reason,
                    }
                }

        # Check path tools (Glob, Grep)
        if tool_name in PATH_TOOLS:
            path = tool_input.get("path", "")
            if path and _is_outside_worktree(path):
                logger.warning(
                    f"Path guard blocked {tool_name} on {path} "
                    f"(outside worktree {worktree_str})"
                )
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": deny_reason,
                    }
                }

        # Check Bash commands for main repo path references
        if tool_name == "Bash":
            command = tool_input.get("command", "")
            if project_root_str in command and worktree_str not in command:
                logger.warning(
                    f"Path guard blocked Bash command referencing main repo: {command[:100]}"
                )
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": (
                            f"This command references the main project directory ({project_root_str}) "
                            f"instead of your worktree ({worktree_str}). "
                            "Use relative paths or paths within your worktree."
                        ),
                    }
                }

        return {}

    return hook
