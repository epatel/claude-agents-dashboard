"""PreToolUse hook that keeps writes scoped to the agent's worktree.

Single-repo mode: writes AND reads are restricted to the worktree. Any path
that lands in the main project checkout (but not the worktree) is denied.

Multi-repo mode: writes are still worktree-only, but reads/searches are
allowed anywhere under the workspace root so an agent can reference sibling
repos. The workspace root is the parent folder containing all subrepos.
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Tools that accept a file_path parameter
FILE_PATH_TOOLS = {"Read", "Edit", "Write"}
# Tools that accept a path parameter
PATH_TOOLS = {"Glob", "Grep"}
# Tools considered "read-only" for scope purposes
READ_ONLY_TOOLS = {"Read", "Glob", "Grep"}


def make_path_guard_hook(worktree_path: Path, workspace_root: Optional[Path] = None):
    """Create a PreToolUse hook that enforces the worktree boundary.

    Args:
        worktree_path: Absolute path to the agent's worktree directory. Writes
            must stay inside this path.
        workspace_root: Optional absolute path to a parent folder containing
            sibling repos. When provided (multi-repo mode), read-only tool
            calls (Read/Glob/Grep) are allowed anywhere under this root;
            only writes remain worktree-scoped. When None, the guard falls
            back to historical single-repo behavior where reads are also
            restricted to the worktree.
    """
    worktree_str = str(worktree_path.resolve())
    # Derive single-repo "project root" for write-scope checks — the main
    # repo is the worktree's grandparent's parent (…/agents-lab/worktrees/<id>).
    project_root = worktree_path.resolve().parent.parent.parent
    project_root_str = str(project_root)
    workspace_root_str = str(workspace_root.resolve()) if workspace_root else None

    def _resolve(path_str: str) -> Optional[str]:
        if not path_str:
            return None
        try:
            return str(Path(path_str).resolve())
        except (ValueError, OSError):
            return None

    def _inside(resolved: str, root: str) -> bool:
        return resolved == root or resolved.startswith(root + "/")

    def _write_denied(resolved: str) -> bool:
        """Block writes that leave the worktree and land in the main checkout."""
        if _inside(resolved, worktree_str):
            return False
        if _inside(resolved, project_root_str):
            return True
        return False

    def _read_denied(resolved: str) -> bool:
        """Block reads that leave the allowed scope.

        Multi-repo mode: anywhere under the workspace root is fine.
        Single-repo mode: only the worktree is fine if the path is inside
        the main project.
        """
        if _inside(resolved, worktree_str):
            return False
        if workspace_root_str and _inside(resolved, workspace_root_str):
            return False
        if _inside(resolved, project_root_str):
            return True
        return False

    write_deny_reason = (
        "This path is in the main project checkout, not your worktree. "
        f"Your worktree is at {worktree_str}. Writes must stay inside it."
    )
    read_deny_reason = (
        "This path is outside the allowed read scope "
        f"(worktree: {worktree_str}"
        + (f", workspace: {workspace_root_str}" if workspace_root_str else "")
        + "). Use paths inside that scope."
    )

    async def hook(hook_input, tool_use_id, context):
        tool_name = hook_input.get("tool_name", "")
        tool_input = hook_input.get("tool_input", {})

        # Pick the path field depending on tool shape
        path_str = ""
        if tool_name in FILE_PATH_TOOLS:
            path_str = tool_input.get("file_path", "")
        elif tool_name in PATH_TOOLS:
            path_str = tool_input.get("path", "")

        if path_str:
            resolved = _resolve(path_str)
            if resolved is not None:
                is_read = tool_name in READ_ONLY_TOOLS
                denied = _read_denied(resolved) if is_read else _write_denied(resolved)
                if denied:
                    logger.warning(
                        f"Path guard blocked {tool_name} on {path_str} "
                        f"(worktree {worktree_str}, workspace {workspace_root_str})"
                    )
                    return {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "deny",
                            "permissionDecisionReason": (
                                read_deny_reason if is_read else write_deny_reason
                            ),
                        }
                    }

        # Check Bash commands for references to paths outside the allowed scope.
        # This is best-effort — we only flag when the command clearly mentions
        # the main project root without the worktree (single-repo heuristic).
        # In multi-repo mode the parent-root heuristic would produce false
        # positives on every sibling-repo read, so we skip it.
        if tool_name == "Bash" and not workspace_root_str:
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
