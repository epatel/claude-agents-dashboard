"""Worktree boundary predicates, plus the Claude PreToolUse hook built on them.

Single-repo mode: writes AND reads are restricted to the worktree. Any path
that lands in the main project checkout (but not the worktree) is denied.

Multi-repo mode: writes are still worktree-only, but reads/searches are
allowed anywhere under the workspace root so an agent can reference sibling
repos. The workspace root is the parent folder containing all subrepos.

`PathScope` holds the decision logic so the Claude hook
(`make_path_guard_hook`) and the Kimi ACP permission handler
(`kimi_session._decide_permission`) share one implementation of "is this path
inside the agent's boundary" — see AGENT_FILES/AUDIT.md finding #15.
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


class PathScope:
    """The path boundary of one agent run.

    Args:
        worktree_path: Absolute path to the agent's worktree. Writes must stay
            inside it; relative paths resolve against it (it is the agent's
            cwd, not the dashboard process's).
        workspace_root: Optional parent folder containing sibling repos
            (multi-repo mode). When given, reads are allowed anywhere under it.
        strict_writes: When True, a write outside the worktree is denied
            wherever it points. When False (the historical Claude-hook
            behavior), only writes that land in the main project checkout are
            denied — a write to, say, `/tmp` is left alone.
    """

    def __init__(self, worktree_path: Path, workspace_root: Optional[Path] = None,
                 strict_writes: bool = False):
        resolved_worktree = Path(worktree_path).resolve()
        self.worktree = str(resolved_worktree)
        # Derive the single-repo "project root" for write-scope checks — the
        # main repo is the worktree's great-grandparent
        # (…/<project>/agents-lab/worktrees/<id>).
        self.project_root = str(resolved_worktree.parent.parent.parent)
        self.workspace_root = (
            str(Path(workspace_root).resolve()) if workspace_root else None
        )
        self.strict_writes = strict_writes

    def resolve(self, path_str: str) -> Optional[str]:
        """Absolute, symlink-resolved form of a tool-supplied path, or None.

        `~` is expanded and relative paths are joined onto the worktree, so a
        path the agent meant relative to its cwd is not mistaken for one
        outside the boundary (or vice versa).
        """
        if not path_str or not isinstance(path_str, str):
            return None
        try:
            path = Path(path_str).expanduser()
            if not path.is_absolute():
                path = Path(self.worktree) / path
            return str(path.resolve())
        except (ValueError, OSError, RuntimeError):
            return None

    @staticmethod
    def _inside(resolved: str, root: str) -> bool:
        return resolved == root or resolved.startswith(root + "/")

    def inside_worktree(self, resolved: str) -> bool:
        return self._inside(resolved, self.worktree)

    def write_denied(self, resolved: str) -> bool:
        """Should a write to this resolved path be refused?"""
        if self.inside_worktree(resolved):
            return False
        if self.strict_writes:
            return True
        return self._inside(resolved, self.project_root)

    def read_denied(self, resolved: str) -> bool:
        """Should a read/search of this resolved path be refused?

        Multi-repo mode: anywhere under the workspace root is fine.
        Single-repo mode: only the worktree is fine if the path is inside
        the main project.
        """
        if self.inside_worktree(resolved):
            return False
        if self.workspace_root and self._inside(resolved, self.workspace_root):
            return False
        return self._inside(resolved, self.project_root)

    @property
    def write_deny_reason(self) -> str:
        if self.strict_writes:
            return (
                "This path is outside your worktree. Your worktree is at "
                f"{self.worktree}. Writes must stay inside it."
            )
        return (
            "This path is in the main project checkout, not your worktree. "
            f"Your worktree is at {self.worktree}. Writes must stay inside it."
        )

    @property
    def read_deny_reason(self) -> str:
        return (
            "This path is outside the allowed read scope "
            f"(worktree: {self.worktree}"
            + (f", workspace: {self.workspace_root}" if self.workspace_root else "")
            + "). Use paths inside that scope."
        )


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
    scope = PathScope(worktree_path, workspace_root=workspace_root)
    worktree_str = scope.worktree
    project_root_str = scope.project_root
    workspace_root_str = scope.workspace_root

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
            resolved = scope.resolve(path_str)
            if resolved is not None:
                is_read = tool_name in READ_ONLY_TOOLS
                denied = (
                    scope.read_denied(resolved) if is_read
                    else scope.write_denied(resolved)
                )
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
                                scope.read_deny_reason if is_read
                                else scope.write_deny_reason
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
