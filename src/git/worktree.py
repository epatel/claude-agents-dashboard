from pathlib import Path
from .operations import run_git, get_current_branch


async def create_worktree(repo: Path, worktree_dir: Path, branch_name: str) -> tuple[Path, str, str]:
    """Create a git worktree with a new branch off the current branch.

    Returns (worktree_path, base_branch, base_commit) so the caller can
    record which branch and exact commit the worktree was created from.
    """
    current = await get_current_branch(repo)
    worktree_path = worktree_dir / branch_name.replace("/", "-")

    # Check if the base branch actually exists
    try:
        await run_git(repo, "rev-parse", "--verify", current)
    except Exception:
        # Base branch doesn't exist - likely an empty repository
        # Try to create an initial commit to establish the branch
        try:
            # Create a minimal README to establish the repository
            readme_path = repo / "README.md"
            if not readme_path.exists():
                readme_path.write_text("# Project\n\nThis repository was initialized by Claude Agents Dashboard.\n")
                await run_git(repo, "add", "README.md")
                await run_git(repo, "commit", "-m", "Initial commit")
        except Exception as e:
            raise ValueError(f"Repository at {repo} appears to be empty with no commits. Please initialize it with at least one commit, or ensure the target directory is a valid git repository.") from e

    # Capture the exact commit SHA before creating the worktree
    base_commit = await run_git(repo, "rev-parse", current)

    await run_git(repo, "worktree", "add", str(worktree_path), "-b", branch_name, current)
    return worktree_path, current, base_commit


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
