"""Stale-worktree discovery and cleanup for WorkflowService.

A mixin: it relies on the services WorkflowService.__init__ sets up.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..domain.item_state import ItemState, UnknownStateEncoding, from_columns

# Logged under the WorkflowService module's name, as before the split.
logger = logging.getLogger(__name__.rsplit(".", 1)[0] + ".workflow_service")


class StaleWorktreeMixin:
    """find_stale_worktrees / cleanup_stale_worktree and their helpers."""

    async def find_stale_worktrees(self) -> List[Dict[str, Any]]:
        """Find worktrees whose items are in a terminal state or missing from DB.

        In multi-repo mode iterates each subrepo's worktrees; in single-repo
        mode asks the one target_project for its list.
        """
        stale = []
        for wt in await self._all_worktree_records():
            entry = await self._stale_worktree_entry(wt)
            if entry:
                stale.append(entry)
        return stale

    async def _all_worktree_records(self) -> List[Dict[str, Any]]:
        """Worktree records across all repos (multi-repo records carry ``_source_repo``)."""
        from ..git.worktree import list_worktrees

        if not self.git.is_multi():
            return list(await list_worktrees(self.git.target_project))
        return await self._multi_repo_worktree_records(list_worktrees)

    async def _multi_repo_worktree_records(self, list_worktrees) -> List[Dict[str, Any]]:
        """Each subrepo's worktree records, tagged with ``_source_repo``; a repo
        whose worktrees can't be listed is skipped with a warning."""
        worktree_records: List[Dict[str, Any]] = []
        for repo_name in (self.git.repos or []):
            base = self.git.base_repo_path(repo_name)
            try:
                for wt in await list_worktrees(base):
                    wt["_source_repo"] = repo_name
                    worktree_records.append(wt)
            except Exception as e:
                logger.warning(f"Failed to list worktrees for repo {repo_name}: {e}")
        return worktree_records

    async def _stale_worktree_entry(self, wt: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """The stale-worktree record for an agent worktree, or None if it is still in use."""
        path = wt.get("path", "")
        branch = wt.get("branch", "")
        # Only check agent worktrees (refs/heads/agent/...)
        if not branch.startswith("refs/heads/agent/"):
            return None
        branch_name = branch.removeprefix("refs/heads/")
        # Extract item_id from branch name "agent/{item_id}"
        item_id = branch_name.removeprefix("agent/")
        if not item_id:
            return None

        item = await self.db.get_item(item_id)
        if not item:
            # Item deleted from DB but worktree remains
            return {"item_id": item_id, "branch_name": branch_name, "worktree_path": path, "reason": "Item no longer exists in database"}

        reason = self._stale_reason(item_id, item)
        if not reason:
            return None
        title = item.get("title", item_id[:8])
        return {"item_id": item_id, "title": title, "branch_name": branch_name, "worktree_path": path, "reason": reason}

    def _stale_reason(self, item_id: str, item: Dict[str, Any]) -> Optional[str]:
        """Why an existing item's worktree is stale (inactive state, no running
        session), or None if it isn't."""
        has_session = item_id in self.sessions.sessions
        try:
            state = from_columns(item.get("column_name", ""), item.get("status"))
        except UnknownStateEncoding:
            return None  # unknown legacy encoding — leave alone, audit logs it on startup
        if has_session:
            return None
        if state in {ItemState.CANCELLED, ItemState.DONE, ItemState.ARCHIVED}:
            return f"Item is {state.value}"
        if state is ItemState.BACKLOG:
            return "Item is in todo with no active agent"
        return None

    async def cleanup_stale_worktree(self, item_id: str) -> Dict[str, Any]:
        """Clean up a stale worktree and clear git metadata on the item."""
        item = await self.db.get_item(item_id)
        branch_name = f"agent/{item_id}"
        # Default worktree path — matches what create_or_reuse_worktree would have built
        item_repo = item.get("repo") if item else None
        worktree_path = self.git.worktree_path_for(item_id, branch_name, item_repo)

        # Use item's stored values if available
        if item:
            branch_name = item.get("branch_name") or branch_name
            worktree_path = Path(item.get("worktree_path") or str(worktree_path))

        await self.git.cleanup_item_resources(str(worktree_path), branch_name, repo=item_repo)

        # Clear git metadata on the item if it still exists
        if item:
            updated = await self.items.update_fields(
                item_id, worktree_path=None, branch_name=None, base_branch=None, base_commit=None
            )
            await self.notifications.broadcast_item_updated(updated)

        return {"ok": True, "item_id": item_id}
