from pathlib import Path
from .operations import run_git, get_current_branch


async def create_worktree(repo: Path, worktree_dir: Path, branch_name: str) -> tuple[Path, str]:
    """Create a git worktree with a new branch off the current branch.

    Returns (worktree_path, base_branch) so the caller can record which
    branch the worktree was created from.
    """
    current = await get_current_branch(repo)
    worktree_path = worktree_dir / branch_name.replace("/", "-")

    await run_git(repo, "worktree", "add", str(worktree_path), "-b", branch_name, current)
    return worktree_path, current


async def remove_worktree(repo: Path, worktree_path: Path) -> None:
    """Remove a git worktree and its branch."""
    await run_git(repo, "worktree", "remove", str(worktree_path), "--force")


async def list_worktrees(repo: Path) -> list[dict]:
    """List all worktrees."""
    output = await run_git(repo, "worktree", "list", "--porcelain")
    worktrees = []
    current = {}
    for line in output.split("\n"):
        if not line.strip():
            if current:
                worktrees.append(current)
                current = {}
            continue
        if line.startswith("worktree "):
            current["path"] = line[9:]
        elif line.startswith("branch "):
            current["branch"] = line[7:]
        elif line == "bare":
            current["bare"] = True
    if current:
        worktrees.append(current)
    return worktrees


async def cleanup_worktree(repo: Path, worktree_path: Path, branch_name: str) -> None:
    """Remove worktree and delete its branch."""
    try:
        await remove_worktree(repo, worktree_path)
    except Exception:
        pass
    try:
        await run_git(repo, "branch", "-D", branch_name)
    except Exception:
        pass
