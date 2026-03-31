import asyncio
import subprocess
from pathlib import Path
import os.path
from ..config import GIT_OPERATION_TIMEOUT, GIT_MERGE_TIMEOUT


async def run_git(cwd: Path, *args: str, timeout: float | None = None) -> str:
    """Run a git command with optional timeout.

    Args:
        cwd: Working directory for git command
        *args: Git command arguments
        timeout: Optional timeout in seconds (defaults to GIT_OPERATION_TIMEOUT)

    Raises:
        subprocess.CalledProcessError: If git command fails
        asyncio.TimeoutError: If command times out
    """
    if timeout is None:
        timeout = GIT_MERGE_TIMEOUT if args and args[0] == "merge" else GIT_OPERATION_TIMEOUT

    try:
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode != 0:
            raise subprocess.CalledProcessError(
                proc.returncode, ["git", *args], stdout, stderr
            )
        return stdout.decode().strip()
    except asyncio.TimeoutError:
        # Kill the process if it's still running
        if proc.returncode is None:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        raise asyncio.TimeoutError(f"Git command timed out after {timeout}s: git {' '.join(args)}")


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
            # Fallback: use whatever HEAD points to (handles empty repos too)
            return await get_current_branch(repo)


async def get_current_branch(repo: Path) -> str:
    """Get the currently checked-out branch name.

    Returns the branch name, or a fallback if HEAD doesn't exist yet
    (e.g. in an empty repo with no commits).
    """
    try:
        return (await run_git(repo, "rev-parse", "--abbrev-ref", "HEAD")).strip()
    except subprocess.CalledProcessError:
        # Empty repo: HEAD exists but points to an unborn branch.
        # Try to read the symbolic ref directly.
        try:
            ref = (await run_git(repo, "symbolic-ref", "--short", "HEAD")).strip()
            return ref
        except subprocess.CalledProcessError:
            return "main"


async def get_diff(repo: Path, branch: str, base: str | None = None,
                   worktree_path: Path | None = None, base_commit: str | None = None) -> str:
    """Get diff including both committed and uncommitted changes.

    If worktree_path is given, diffs the worktree working directory against base.
    Otherwise diffs the branch ref against base.

    Args:
        base_commit: If provided, use this exact commit SHA instead of the base
            branch name. This ensures diffs are stable even when the base branch
            moves forward (e.g., after other items are merged).
    """
    # Prefer base_commit (immutable SHA) over base branch name (moving target)
    diff_base = base_commit or base
    if diff_base is None:
        diff_base = await get_main_branch(repo)

    if worktree_path and worktree_path.exists():
        # Diff base against the worktree's working directory (includes uncommitted changes)
        # First get committed diff
        committed = ""
        try:
            committed = await run_git(repo, "diff", diff_base, branch)
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
                    content = await asyncio.to_thread((worktree_path / f).read_text)
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
        return await run_git(repo, "diff", diff_base, branch)


async def get_changed_files(repo: Path, branch: str, base: str | None = None,
                            worktree_path: Path | None = None, base_commit: str | None = None) -> list[dict]:
    """Get list of changed files including uncommitted changes.

    Args:
        base_commit: If provided, use this exact commit SHA instead of the base
            branch name for stable results.
    """
    diff_base = base_commit or base
    if diff_base is None:
        diff_base = await get_main_branch(repo)

    status_labels = {"A": "Added", "M": "Modified", "D": "Deleted", "R": "Renamed"}
    files = {}

    # Get committed changes between base and branch
    try:
        output = await run_git(repo, "diff", "--name-status", diff_base, branch)
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


def validate_file_path(file_path: str) -> str:
    """Validate and sanitize file path to prevent path traversal attacks.

    Args:
        file_path: The file path to validate

    Returns:
        str: The sanitized file path

    Raises:
        ValueError: If the path contains invalid patterns
    """
    if not file_path:
        raise ValueError("File path cannot be empty")

    # Remove any null bytes or control characters
    file_path = file_path.replace('\x00', '')

    # Check for absolute paths
    if os.path.isabs(file_path):
        raise ValueError("Absolute paths are not allowed")

    # Check for parent directory traversal patterns
    if '..' in file_path:
        raise ValueError("Path traversal patterns (..) are not allowed")

    # Check for other potentially dangerous patterns
    dangerous_patterns = [
        '~/',  # Home directory expansion
        '//',  # Double slashes
        '\\',  # Windows-style separators
        '\n',  # Newlines
        '\r',  # Carriage returns
    ]

    for pattern in dangerous_patterns:
        if pattern in file_path:
            raise ValueError(f"Invalid character sequence '{pattern}' in path")

    # Normalize the path and ensure it doesn't start with /
    normalized = os.path.normpath(file_path)
    if normalized.startswith('/'):
        raise ValueError("Normalized path cannot start with /")

    # Additional check: ensure normalization didn't create .. patterns
    if '..' in normalized:
        raise ValueError("Normalized path contains parent directory references")

    return normalized


async def get_file_content(repo: Path, branch: str, file_path: str) -> str:
    """Get file content at a specific branch."""
    # Validate the file path to prevent path traversal attacks
    validated_path = validate_file_path(file_path)
    return await run_git(repo, "show", f"{branch}:{validated_path}")


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
                       worktree_path: Path | None = None,
                       commit_message: str | None = None) -> tuple[bool, str]:
    """Merge branch into base. Returns (success, message).

    If worktree_path is given, first commits any uncommitted changes there.
    If commit_message is provided, it is used instead of the default generic message.
    """
    if base is None:
        base = await get_current_branch(repo)

    stashed = False
    try:
        # Commit uncommitted changes in the worktree first
        if worktree_path and worktree_path.exists():
            msg = commit_message or f"Agent work on {branch}"
            committed = await commit_worktree_changes(worktree_path, msg)

        # Stash any dirty state in the base repo before checkout
        status = await run_git(repo, "status", "--porcelain")
        if status.strip():
            await run_git(repo, "stash", "push", "-m", f"auto-stash before merge of {branch}")
            stashed = True

        # Checkout base in the main repo
        await run_git(repo, "checkout", base)

        # Perform the merge with explicit timeout
        merge_msg = commit_message or f"Merge {branch} into {base}"
        await run_git(repo, "merge", branch, "--no-ff",
                      "-m", merge_msg, timeout=GIT_MERGE_TIMEOUT)
        # Get the merge commit SHA
        sha = (await run_git(repo, "rev-parse", "HEAD")).strip()
        return True, sha
    except asyncio.TimeoutError as e:
        # Timeout during merge operation
        try:
            await run_git(repo, "merge", "--abort")
        except (subprocess.CalledProcessError, asyncio.TimeoutError):
            pass
        return False, f"Merge operation timed out: {str(e)}"
    except subprocess.CalledProcessError as e:
        # Conflict or other git error — abort the merge
        try:
            await run_git(repo, "merge", "--abort")
        except (subprocess.CalledProcessError, asyncio.TimeoutError):
            pass
        return False, e.stderr.decode() if e.stderr else str(e)
    finally:
        # Restore stashed changes
        if stashed:
            try:
                await run_git(repo, "stash", "pop")
            except (subprocess.CalledProcessError, asyncio.TimeoutError):
                logger.warning("Failed to restore stashed changes after merge")
