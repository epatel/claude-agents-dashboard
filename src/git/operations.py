import asyncio
import subprocess
from pathlib import Path


async def run_git(cwd: Path, *args: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode, ["git", *args], stdout, stderr
        )
    return stdout.decode().strip()


async def get_main_branch(repo: Path) -> str:
    """Detect the main branch name (main or master)."""
    try:
        await run_git(repo, "rev-parse", "--verify", "main")
        return "main"
    except subprocess.CalledProcessError:
        try:
            await run_git(repo, "rev-parse", "--verify", "master")
            return "master"
        except subprocess.CalledProcessError:
            # Fallback: use whatever HEAD points to
            return (await run_git(repo, "rev-parse", "--abbrev-ref", "HEAD"))


async def get_diff(repo: Path, branch: str, base: str | None = None, worktree_path: Path | None = None) -> str:
    """Get diff including both committed and uncommitted changes.

    If worktree_path is given, diffs the worktree working directory against base.
    Otherwise diffs the branch ref against base.
    """
    if base is None:
        base = await get_main_branch(repo)

    if worktree_path and worktree_path.exists():
        # Diff base against the worktree's working directory (includes uncommitted changes)
        # First get committed diff
        committed = ""
        try:
            committed = await run_git(repo, "diff", base, branch)
        except subprocess.CalledProcessError:
            pass

        # Then get uncommitted changes in the worktree (staged + unstaged + new files)
        uncommitted = ""
        try:
            uncommitted = await run_git(worktree_path, "diff", "HEAD")
        except subprocess.CalledProcessError:
            pass

        # Also get new untracked files
        new_files_diff = ""
        try:
            untracked = await run_git(worktree_path, "ls-files", "--others", "--exclude-standard")
            for f in untracked.split("\n"):
                if not f.strip():
                    continue
                try:
                    content = (worktree_path / f).read_text()
                    new_files_diff += f"diff --git a/{f} b/{f}\nnew file mode 100644\n--- /dev/null\n+++ b/{f}\n"
                    lines = content.split("\n")
                    new_files_diff += f"@@ -0,0 +1,{len(lines)} @@\n"
                    new_files_diff += "\n".join(f"+{line}" for line in lines) + "\n"
                except Exception:
                    pass
        except subprocess.CalledProcessError:
            pass

        # Combine: committed changes + uncommitted changes + new files
        parts = [p for p in [committed, uncommitted, new_files_diff] if p.strip()]
        return "\n".join(parts)
    else:
        return await run_git(repo, "diff", base, branch)


async def get_changed_files(repo: Path, branch: str, base: str | None = None, worktree_path: Path | None = None) -> list[dict]:
    """Get list of changed files including uncommitted changes."""
    if base is None:
        base = await get_main_branch(repo)

    status_labels = {"A": "Added", "M": "Modified", "D": "Deleted", "R": "Renamed"}
    files = {}

    # Get committed changes between base and branch
    try:
        output = await run_git(repo, "diff", "--name-status", base, branch)
        for line in output.split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t", 1)
            status_code = parts[0][0]
            path = parts[1] if len(parts) > 1 else ""
            files[path] = status_code
    except subprocess.CalledProcessError:
        pass

    # Get uncommitted changes in worktree
    if worktree_path and worktree_path.exists():
        try:
            output = await run_git(worktree_path, "diff", "--name-status", "HEAD")
            for line in output.split("\n"):
                if not line.strip():
                    continue
                parts = line.split("\t", 1)
                status_code = parts[0][0]
                path = parts[1] if len(parts) > 1 else ""
                files[path] = status_code
        except subprocess.CalledProcessError:
            pass

        # Get untracked files
        try:
            untracked = await run_git(worktree_path, "ls-files", "--others", "--exclude-standard")
            for f in untracked.split("\n"):
                if f.strip():
                    files[f] = "A"
        except subprocess.CalledProcessError:
            pass

    return [
        {"status": s, "status_label": status_labels.get(s, s), "path": p}
        for p, s in sorted(files.items())
    ]


async def get_file_content(repo: Path, branch: str, file_path: str) -> str:
    """Get file content at a specific branch."""
    return await run_git(repo, "show", f"{branch}:{file_path}")


async def commit_worktree_changes(worktree_path: Path, message: str) -> bool:
    """Commit any uncommitted changes in a worktree. Returns True if changes were committed."""
    # Add all changes including new files
    try:
        await run_git(worktree_path, "add", "-A")
    except subprocess.CalledProcessError:
        return False

    # Check if there's anything to commit
    try:
        await run_git(worktree_path, "diff", "--cached", "--quiet")
        return False  # No staged changes
    except subprocess.CalledProcessError:
        pass  # Has staged changes — commit them

    try:
        await run_git(worktree_path, "commit", "-m", message)
        return True
    except subprocess.CalledProcessError:
        return False


async def merge_branch(repo: Path, branch: str, base: str | None = None,
                       worktree_path: Path | None = None) -> tuple[bool, str]:
    """Merge branch into base. Returns (success, message).

    If worktree_path is given, first commits any uncommitted changes there.
    """
    if base is None:
        base = await get_main_branch(repo)

    # Commit uncommitted changes in the worktree first
    if worktree_path and worktree_path.exists():
        committed = await commit_worktree_changes(
            worktree_path, f"Agent work on {branch}"
        )

    # Checkout base in the main repo
    await run_git(repo, "checkout", base)

    try:
        output = await run_git(repo, "merge", branch, "--no-ff",
                               "-m", f"Merge {branch} into {base}")
        return True, output
    except subprocess.CalledProcessError as e:
        # Conflict — abort the merge
        try:
            await run_git(repo, "merge", "--abort")
        except subprocess.CalledProcessError:
            pass
        return False, e.stderr.decode() if e.stderr else str(e)
