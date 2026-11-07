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

    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await communicate_or_kill(proc, timeout)
    except asyncio.TimeoutError:
        raise asyncio.TimeoutError(f"Git command timed out after {timeout}s: git {' '.join(args)}")
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode, ["git", *args], stdout, stderr
        )
    return stdout.decode().strip()


async def communicate_or_kill(proc, timeout: float) -> tuple[bytes, bytes]:
    """``proc.communicate()`` with a timeout; on timeout stop the process and re-raise.

    Stopping is terminate, then kill if it hasn't exited within 5s.
    """
    try:
        return await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        if proc.returncode is None:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        raise


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
    diff_base = await _resolve_diff_base(repo, base, base_commit)
    if not (worktree_path and worktree_path.exists()):
        return await run_git(repo, "diff", diff_base, branch)

    # Diff base against the worktree's working directory: committed changes +
    # uncommitted changes (staged + unstaged) + new untracked files.
    committed = await _git_or_empty(repo, "diff", diff_base, branch)
    uncommitted = await _git_or_empty(worktree_path, "diff", "HEAD")
    new_files_diff = ""
    for path, full_path in await _untracked_files(worktree_path):
        try:
            content = await asyncio.to_thread(full_path.read_text)
        except Exception:
            continue
        new_files_diff += _new_file_diff(path, content)

    parts = [p for p in [committed, uncommitted, new_files_diff] if p.strip()]
    return "\n".join(parts)


async def get_changed_files(repo: Path, branch: str, base: str | None = None,
                            worktree_path: Path | None = None, base_commit: str | None = None) -> list[dict]:
    """Get list of changed files including uncommitted changes.

    Args:
        base_commit: If provided, use this exact commit SHA instead of the base
            branch name for stable results.
    """
    diff_base = await _resolve_diff_base(repo, base, base_commit)
    status_labels = {"A": "Added", "M": "Modified", "D": "Deleted", "R": "Renamed"}

    # Committed changes between base and branch, then (later entries win)
    # uncommitted and untracked changes in the worktree.
    files = _parse_name_status(await _git_or_empty(repo, "diff", "--name-status", diff_base, branch))
    if worktree_path and worktree_path.exists():
        files.update(_parse_name_status(
            await _git_or_empty(worktree_path, "diff", "--name-status", "HEAD")
        ))
        for path, _ in await _untracked_files(worktree_path):
            files[path] = "A"

    return [
        {"status": s, "status_label": status_labels.get(s, s), "path": p}
        for p, s in sorted(files.items())
    ]


async def _resolve_diff_base(repo: Path, base: str | None, base_commit: str | None) -> str:
    """Prefer base_commit (immutable SHA) over the base branch name (a moving target)."""
    diff_base = base_commit or base
    if diff_base is None:
        diff_base = await get_main_branch(repo)
    return diff_base


async def _git_or_empty(cwd: Path, *args: str) -> str:
    """run_git output, or '' if the git command fails."""
    try:
        return await run_git(cwd, *args)
    except subprocess.CalledProcessError:
        return ""


def _parse_name_status(output: str) -> dict[str, str]:
    """``git diff --name-status`` output as {path: one-letter status}."""
    files = {}
    for line in output.split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        files[parts[1] if len(parts) > 1 else ""] = parts[0][0]
    return files


async def _untracked_files(worktree_path: Path) -> list[tuple[str, Path]]:
    """Untracked, non-ignored files as (validated relative path, resolved path).

    Paths that fail validation or resolve outside the worktree are skipped.
    """
    output = await _git_or_empty(worktree_path, "ls-files", "--others", "--exclude-standard")
    root = worktree_path.resolve()
    found = []
    for name in output.split("\n"):
        if not name.strip():
            continue
        try:
            validated = validate_file_path(name.strip())
            full_path = (worktree_path / validated).resolve()
        except (ValueError, OSError):
            continue
        if full_path == root or str(full_path).startswith(str(root) + os.sep):
            found.append((validated, full_path))
    return found


def _new_file_diff(path: str, content: str) -> str:
    """A unified diff that adds ``path`` with ``content``."""
    lines = content.split("\n")
    return (
        f"diff --git a/{path} b/{path}\nnew file mode 100644\n--- /dev/null\n+++ b/{path}\n"
        f"@@ -0,0 +1,{len(lines)} @@\n"
        + "\n".join(f"+{line}" for line in lines) + "\n"
    )


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


async def rebase_branch(worktree_path: Path, base: str) -> tuple[bool, str]:
    """Attempt to rebase the current branch onto base in the worktree.

    Returns (success, message). On conflict, aborts the rebase and returns False.
    """
    try:
        await run_git(worktree_path, "rebase", base, timeout=GIT_MERGE_TIMEOUT)
        return True, "Rebase succeeded"
    except subprocess.CalledProcessError as e:
        # Rebase failed (conflict) — abort it
        try:
            await run_git(worktree_path, "rebase", "--abort")
        except (subprocess.CalledProcessError, asyncio.TimeoutError):
            pass
        stderr = e.stderr.decode() if e.stderr else str(e)
        return False, f"Rebase conflict: {stderr[:200]}"
    except asyncio.TimeoutError:
        try:
            await run_git(worktree_path, "rebase", "--abort")
        except (subprocess.CalledProcessError, asyncio.TimeoutError):
            pass
        return False, "Rebase timed out"


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
    """Merge `branch` into `base` inside `repo`. Returns (success, message).

    `base` is REQUIRED. The agent's worktree was forked from a specific
    branch, and the only correct merge target is that exact branch — recorded
    on the item as `base_branch` at worktree creation time. We deliberately
    don't fall back to "the repo's current HEAD" or "main" here: silent
    fallbacks were the source of the bug where agents started on a feature
    branch ended up merged into `main`.

    If `worktree_path` is given, any uncommitted changes there are committed
    first. If `commit_message` is provided, it is used instead of a default.

    Side effects on `repo`: this temporarily checks out `base` to perform the
    merge, then restores whichever branch was previously checked out — so the
    user's working state in the shared target repo is left as we found it
    (best-effort; failure to restore is swallowed).
    """
    if not base:
        return False, (
            "merge_branch requires an explicit base branch. The worktree's "
            "source branch (item.base_branch) was not provided — refusing to "
            "guess. Pass the branch the agent forked from."
        )

    # Snapshot the repo's currently checked-out branch so we can restore it
    # after the merge. Only restore if it's different from `base`, otherwise
    # the post-merge state is already correct.
    try:
        original_head = await get_current_branch(repo)
    except Exception:
        original_head = None

    try:
        # Commit uncommitted changes in the worktree first
        if worktree_path and worktree_path.exists():
            msg = commit_message or f"Agent work on {branch}"
            committed = await commit_worktree_changes(worktree_path, msg)

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
        # Best-effort restore of the user's previously checked-out branch.
        # Without this, every merge would leave the shared target repo sitting
        # on `base` (typically `main`), which then cascades: the next item
        # created here would record `base_branch = main` because
        # create_worktree snapshots HEAD at creation time.
        if original_head and original_head != base:
            try:
                await run_git(repo, "checkout", original_head)
            except (subprocess.CalledProcessError, asyncio.TimeoutError):
                pass
