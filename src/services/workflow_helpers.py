"""Small helpers shared by WorkflowService and its mixins."""

from pathlib import Path
from typing import Any, Dict, Optional


def _worktree_of(item: Dict[str, Any]) -> Optional[Path]:
    """The item's worktree path, or None if it has none recorded."""
    return Path(item["worktree_path"]) if item.get("worktree_path") else None
