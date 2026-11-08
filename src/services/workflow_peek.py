"""Worktree peek for WorkflowService: lets an agent read what the other running
agents have changed in their worktrees (the peek_worktree tool).

A mixin: it relies on the services WorkflowService.__init__ sets up.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

# Logged under the WorkflowService module's name, as before the split.
logger = logging.getLogger(__name__.rsplit(".", 1)[0] + ".workflow_service")

# Caps for the peek_worktree tool — a peek must stay cheap enough that an
# agent can afford to call it before every shared-file edit.
_PEEK_MAX_FILES_PER_ITEM = 40
_PEEK_MAX_FILES_DETAIL = 200
_PEEK_MAX_DIFF_LINES = 400


class WorktreePeekMixin:
    """peek_worktree and its rendering helpers."""

    def _create_on_peek_worktree_callback(self, item_id: str):
        """Callback backing the peek_worktree tool.

        Closes over the caller's item_id so the peek can flag which of the
        other agents' in-flight files collide with the caller's own.
        """
        async def on_peek_worktree(target_item_id: Optional[str] = None,
                                   path: Optional[str] = None) -> str:
            return await self.peek_worktree(item_id, target_item_id, path)
        return on_peek_worktree

    async def _active_worktree_items(self) -> List[Dict[str, Any]]:
        """Board items whose worktree still exists on disk."""
        items = await self.db.get_items_with_worktrees()
        return [i for i in items if Path(i["worktree_path"]).exists()]

    async def _changed_paths(self, item: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Changed files for one item's worktree; [] when git can't answer."""
        try:
            return await self.git.worktree_changes(
                Path(item["worktree_path"]),
                item.get("branch_name") or "HEAD",
                base_branch=item.get("base_branch"),
                base_commit=item.get("base_commit"),
            )
        except Exception as e:
            logger.warning(f"peek_worktree: could not read {item.get('id')}: {e}")
            return []

    def _peek_item_header(self, item: Dict[str, Any]) -> str:
        status = f" [{item['status']}]" if item.get("status") else ""
        repo = f" repo={item['repo']}" if item.get("repo") else ""
        branch = item.get("branch_name") or "?"
        return (
            f"## [{item.get('id')}] {item.get('title', '')}"
            f" ({item.get('column_name')}{status}) branch={branch}{repo}"
        )

    async def peek_worktree(self, self_item_id: Optional[str],
                            target_item_id: Optional[str] = None,
                            path: Optional[str] = None) -> str:
        """Render another agent's in-flight worktree changes as text."""
        active = await self._active_worktree_items()
        by_id = {i["id"]: i for i in active}
        own_paths = await self._own_changed_paths(by_id.get(self_item_id) if self_item_id else None)

        if not target_item_id:
            return await self._peek_overview(
                [i for i in active if i["id"] != self_item_id], own_paths
            )
        item = by_id.get(target_item_id)
        if not item:
            return self._no_active_worktree(target_item_id, active, self_item_id)
        if path:
            return await self._peek_file_diff(item, path)
        return await self._peek_item(item, own_paths)

    @staticmethod
    def _no_active_worktree(target_item_id: str, active: List[Dict[str, Any]],
                            self_item_id: Optional[str]) -> str:
        known = ", ".join(i["id"] for i in active if i["id"] != self_item_id)
        return (
            f"No active worktree for item {target_item_id}. "
            f"Worktrees on disk right now: {known or '(none)'}."
        )

    async def _own_changed_paths(self, own_item: Optional[Dict[str, Any]]) -> set:
        """Paths the caller's own worktree changes (empty if it has none on disk)."""
        if not own_item:
            return set()
        return {f["path"] for f in await self._changed_paths(own_item)}

    @staticmethod
    def _peek_file_lines(files: List[Dict[str, Any]], marked: set, limit: int) -> List[str]:
        """One line per changed file (capped at ``limit``), flagging files in ``marked``."""
        lines = []
        for f in files[:limit]:
            mark = "  <-- YOU ARE ALSO CHANGING THIS" if f["path"] in marked else ""
            lines.append(f"  {f['status']} {f['path']}{mark}")
        if len(files) > limit:
            lines.append(f"  ... and {len(files) - limit} more")
        return lines

    async def _peek_item(self, item: Dict[str, Any], own_paths: set) -> str:
        """Full changed-file list for one other agent's worktree."""
        files = await self._changed_paths(item)
        lines = [self._peek_item_header(item), f"{len(files)} changed file(s)"]
        lines += self._peek_file_lines(files, own_paths, _PEEK_MAX_FILES_DETAIL)
        lines.append("")
        lines.append(
            f"For the actual diff of one file: peek_worktree(item_id=\"{item['id']}\", "
            "path=\"<file>\")."
        )
        return "\n".join(lines)

    async def _peek_overview(self, others: List[Dict[str, Any]], own_paths: set) -> str:
        """Summary of every other active worktree, with overlapping files called out."""
        if not others:
            return (
                "No other agent has a worktree on disk right now — nothing in "
                "flight to collide with."
            )

        lines: List[str] = []
        overlaps: Dict[str, List[str]] = {}
        for item in others:
            files = await self._changed_paths(item)
            shared = [f["path"] for f in files if f["path"] in own_paths]
            if shared:
                overlaps[item["id"]] = shared
            lines.append(self._peek_item_header(item))
            if not files:
                lines.append("  (no changes yet)")
            lines += self._peek_file_lines(files, set(shared), _PEEK_MAX_FILES_PER_ITEM)
            lines.append("")

        header = [f"Active worktrees besides yours: {len(others)}"]
        header += self._peek_conflict_warning(overlaps)
        header.append("")
        return "\n".join(header + lines).rstrip() + (
            "\n\nFull file list: peek_worktree(item_id=\"<id>\"). "
            "One file's diff: peek_worktree(item_id=\"<id>\", path=\"<file>\")."
        )

    @staticmethod
    def _peek_conflict_warning(overlaps: Dict[str, List[str]]) -> List[str]:
        """The CONFLICT RISK block for files this agent shares with others (or nothing)."""
        if not overlaps:
            return []
        warning = ["", "CONFLICT RISK - files you and another agent are both changing:"]
        for other_id, shared in overlaps.items():
            warning.append(f"  [{other_id}] {', '.join(shared)}")
        warning.append(
            "Read their version before you edit further (peek_worktree with "
            "item_id + path), and keep your change compatible or narrow it."
        )
        return warning

    async def _peek_file_diff(self, item: Dict[str, Any], path: str) -> str:
        """One file's diff from another agent's worktree, capped."""
        try:
            diff = await self.git.worktree_path_diff(
                Path(item["worktree_path"]), path,
                base_branch=item.get("base_branch"),
                base_commit=item.get("base_commit"),
            )
        except ValueError as e:
            return f"Invalid path {path!r}: {e}"
        except Exception as e:
            logger.warning(f"peek_worktree: diff failed for {item.get('id')}/{path}: {e}")
            return f"Could not read {path} from item {item['id']}: {e}"

        header = f"{self._peek_item_header(item)}\nFile: {path}\n"
        if not diff.strip():
            return header + "(no changes to this file in that worktree)"
        diff_lines = diff.split("\n")
        if len(diff_lines) > _PEEK_MAX_DIFF_LINES:
            diff = "\n".join(diff_lines[:_PEEK_MAX_DIFF_LINES])
            diff += f"\n... diff truncated ({len(diff_lines) - _PEEK_MAX_DIFF_LINES} more lines)"
        return header + diff
