"""Git service for handling git operations and worktree management."""

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from ..git.worktree import create_worktree, cleanup_worktree
from ..git.operations import (
    merge_branch,
    rebase_branch,
    run_git,
    get_changed_files,
    get_main_branch,
    validate_file_path,
)

logger = logging.getLogger(__name__)


class GitService:
    """Handles git operations, worktree management, and branch operations.

    In single-repo mode `target_project` is itself the git repo and `repos` is
    None. In multi-repo mode `target_project` is a parent folder and `repos` is
    the list of git subdirectories; each item picks which one to operate on.
    """

    def __init__(self, target_project: Path, worktree_dir: Path,
                 repos: Optional[list[str]] = None):
        self.target_project = target_project
        self.worktree_dir = worktree_dir
        self.worktree_dir.mkdir(exist_ok=True)
        self.repos = repos  # None = single; list[str] = multi

    def is_multi(self) -> bool:
        return bool(self.repos)

    def base_repo_path(self, repo: Optional[str]) -> Path:
        """Resolve the git repo path for a given item's `repo` field."""
        if self.is_multi():
            if not repo:
                raise ValueError(
                    "Multi-repo mode: item has no 'repo' — cannot resolve base repo"
                )
            if repo not in (self.repos or []):
                raise ValueError(
                    f"Unknown repo '{repo}'. Known: {self.repos}"
                )
            return self.target_project / repo
        return self.target_project

    def worktree_path_for(self, item_id: str, branch_name: str,
                         repo: Optional[str]) -> Path:
        """On-disk location for an item's worktree."""
        if self.is_multi():
            # Item IDs are globally unique; the {repo}- prefix is just for
            # human readability when listing worktrees/.
            return self.worktree_dir / f"{repo}-{item_id}"
        # Single-repo mode keeps historical naming (agent-{id}) so existing
        # dashboards with live worktrees continue to match.
        return self.worktree_dir / branch_name.replace("/", "-")

    async def create_or_reuse_worktree(self, item_id: str,
                                      existing_worktree_path: Optional[str] = None,
                                      existing_branch_name: Optional[str] = None,
                                      repo: Optional[str] = None) -> Tuple[Path, str, Optional[str], Optional[str]]:
        """Create a new worktree or reuse an existing one.

        Returns:
            Tuple of (worktree_path, branch_name, base_branch, base_commit)

            base_branch is the branch the worktree was forked from. It is
            returned ONLY when a fresh worktree is created — on the reuse
            paths it is None, signalling the caller to preserve whatever
            base_branch was originally recorded on the item. We deliberately
            don't hardcode "main" here: doing so silently rewrote the merge
            target for items started from feature branches.

            base_commit is the SHA of the base branch at creation time (None
            when reusing).
        """
        branch_name = existing_branch_name or f"agent/{item_id}"
        base = self.base_repo_path(repo)

        # Check if we can reuse existing worktree. The item's base_branch
        # was recorded when the worktree was first created — don't touch it.
        if existing_worktree_path and Path(existing_worktree_path).exists():
            worktree_path = Path(existing_worktree_path)
            return worktree_path, branch_name, None, None

        # Check if worktree dir already exists from previous run
        worktree_path = self.worktree_path_for(item_id, branch_name, repo)
        if worktree_path.exists():
            return worktree_path, branch_name, None, None

        # Clean up stale branch if it exists
        try:
            await run_git(base, "branch", "-D", branch_name)
        except Exception:
            pass  # Branch doesn't exist, that's fine

        # Create new worktree
        worktree_path, base_branch, base_commit = await create_worktree(
            base, self.worktree_dir, branch_name, worktree_path=worktree_path,
        )

        return worktree_path, branch_name, base_branch, base_commit

    async def merge_agent_work(self, branch_name: str, base_branch: Optional[str] = None,
                              worktree_path: Optional[Path] = None,
                              commit_message: Optional[str] = None,
                              repo: Optional[str] = None) -> Tuple[bool, str]:
        """Merge agent's work back into the base branch."""
        base = self.base_repo_path(repo)
        try:
            success, message = await merge_branch(
                base,
                branch_name,
                base=base_branch,
                worktree_path=worktree_path,
                commit_message=commit_message,
            )
            return success, message
        except asyncio.TimeoutError as e:
            return False, f"Merge operation timed out: {str(e)}"
        except Exception as e:
            return False, f"Unexpected error during merge: {str(e)}"

    async def rebase_onto_base(self, worktree_path: Path, base_branch: str) -> Tuple[bool, str]:
        """Attempt to rebase the worktree branch onto the base branch."""
        try:
            return await rebase_branch(worktree_path, base_branch)
        except Exception as e:
            return False, f"Rebase failed: {str(e)}"

    async def cleanup_worktree_and_branch(self, worktree_path: Path, branch_name: str,
                                          repo: Optional[str] = None):
        """Clean up worktree and associated branch."""
        base = self.base_repo_path(repo)
        try:
            await cleanup_worktree(base, worktree_path, branch_name)
        except Exception as e:
            logger.warning(f"Worktree cleanup failed for {branch_name}: {e}")
            raise

    async def cleanup_item_resources(self, worktree_path: Optional[str], branch_name: Optional[str],
                                     repo: Optional[str] = None):
        """Clean up all git resources for an item."""
        if worktree_path and branch_name:
            try:
                await self.cleanup_worktree_and_branch(Path(worktree_path), branch_name, repo=repo)
            except Exception as e:
                logger.warning(f"Failed to clean up git resources: {e}")
                # Don't re-raise - we want to continue with other cleanup

    # --- Read-only inspection (backs the agents' peek_worktree tool) ---

    async def worktree_changes(self, worktree_path: Path, branch_name: str,
                               base_branch: Optional[str] = None,
                               base_commit: Optional[str] = None) -> list[dict]:
        """Changed files in a worktree vs. the commit it was forked from.

        Committed and uncommitted changes both count — an agent that has not
        committed yet is still holding those files. Same shape as the review
        dialog's file list: [{"status", "status_label", "path"}].
        """
        return await get_changed_files(
            worktree_path, branch_name, base=base_branch,
            worktree_path=worktree_path, base_commit=base_commit,
        )

    async def worktree_path_diff(self, worktree_path: Path, rel_path: str,
                                 base_branch: Optional[str] = None,
                                 base_commit: Optional[str] = None) -> str:
        """Diff of a single file in a worktree, base vs. working tree.

        `git diff <base> -- <path>` compares the base commit against the working
        directory, so committed and uncommitted edits show up together. Raises
        ValueError for paths that fail validation.
        """
        rel = validate_file_path(rel_path)
        diff_base = base_commit or base_branch
        if diff_base is None:
            diff_base = await get_main_branch(worktree_path)
        try:
            diff = await run_git(worktree_path, "diff", diff_base, "--", rel)
        except subprocess.CalledProcessError:
            diff = ""
        if diff.strip():
            return diff

        # Untracked file: git diff says nothing about it, so synthesize an add.
        full_path = (worktree_path / rel).resolve()
        root = worktree_path.resolve()
        if not str(full_path).startswith(str(root) + "/"):
            return ""
        try:
            if full_path.is_file():
                content = await asyncio.to_thread(full_path.read_text, errors="replace")
                lines = content.split("\n")
                body = "\n".join(f"+{line}" for line in lines)
                return (
                    f"diff --git a/{rel} b/{rel}\nnew file mode 100644\n"
                    f"--- /dev/null\n+++ b/{rel}\n@@ -0,0 +1,{len(lines)} @@\n{body}"
                )
        except Exception as e:
            logger.warning(f"Could not read untracked file {full_path}: {e}")
        return ""
