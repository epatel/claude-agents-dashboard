"""Git service for handling git operations and worktree management."""

import asyncio
import logging
from pathlib import Path
from typing import Optional, Tuple

from ..git.worktree import create_worktree, cleanup_worktree
from ..git.operations import merge_branch, run_git

logger = logging.getLogger(__name__)


class GitService:
    """Handles git operations, worktree management, and branch operations."""

    def __init__(self, target_project: Path, worktree_dir: Path):
        self.target_project = target_project
        self.worktree_dir = worktree_dir
        self.worktree_dir.mkdir(exist_ok=True)

    async def create_or_reuse_worktree(self, item_id: str, existing_worktree_path: Optional[str] = None,
                                      existing_branch_name: Optional[str] = None) -> Tuple[Path, str, str, Optional[str]]:
        """Create a new worktree or reuse an existing one.

        Returns:
            Tuple of (worktree_path, branch_name, base_branch, base_commit)
            base_commit is the SHA of the base branch at creation time (None when reusing).
        """
        branch_name = existing_branch_name or f"agent/{item_id}"

        # Check if we can reuse existing worktree
        if existing_worktree_path and Path(existing_worktree_path).exists():
            worktree_path = Path(existing_worktree_path)
            # Try to determine base branch (fallback to main if unknown)
            base_branch = "main"  # Could be enhanced to detect actual base
            return worktree_path, branch_name, base_branch, None

        # Check if worktree dir already exists from previous run
        worktree_path = self.worktree_dir / branch_name.replace("/", "-")
        if worktree_path.exists():
            base_branch = "main"  # Could be enhanced to detect actual base
            return worktree_path, branch_name, base_branch, None

        # Clean up stale branch if it exists
        try:
            await run_git(self.target_project, "branch", "-D", branch_name)
        except Exception:
            pass  # Branch doesn't exist, that's fine

        # Create new worktree
        worktree_path, base_branch, base_commit = await create_worktree(
            self.target_project, self.worktree_dir, branch_name
        )

        return worktree_path, branch_name, base_branch, base_commit

    async def merge_agent_work(self, branch_name: str, base_branch: Optional[str] = None,
                              worktree_path: Optional[Path] = None,
                              commit_message: Optional[str] = None) -> Tuple[bool, str]:
        """Merge agent's work back into the base branch.

        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            success, message = await merge_branch(
                self.target_project,
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

    async def cleanup_worktree_and_branch(self, worktree_path: Path, branch_name: str):
        """Clean up worktree and associated branch."""
        try:
            await cleanup_worktree(self.target_project, worktree_path, branch_name)
        except Exception as e:
            logger.warning(f"Worktree cleanup failed for {branch_name}: {e}")
            raise

    async def cleanup_item_resources(self, worktree_path: Optional[str], branch_name: Optional[str]):
        """Clean up all git resources for an item."""
        if worktree_path and branch_name:
            try:
                await self.cleanup_worktree_and_branch(Path(worktree_path), branch_name)
            except Exception as e:
                logger.warning(f"Failed to clean up git resources: {e}")
                # Don't re-raise - we want to continue with other cleanup