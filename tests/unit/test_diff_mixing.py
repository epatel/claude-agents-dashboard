"""
Tests to verify whether diffs can get mixed up between items.

The core concern: get_diff() runs `git diff base branch` against the shared
main repo. If another operation (like merge/approve) changes the repo state
concurrently, diffs could be incorrect.
"""
import asyncio
import subprocess
import pytest
from pathlib import Path

from src.git.operations import get_diff, get_changed_files, merge_branch
from src.git.worktree import create_worktree


def _git(repo: Path, *args: str) -> str:
    """Synchronous git helper for test setup."""
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _get_commit_sha(repo: Path, ref: str = "HEAD") -> str:
    """Get the commit SHA for a ref."""
    return _git(repo, "rev-parse", ref)


def _init_repo(path: Path) -> Path:
    """Create a git repo with one initial commit."""
    path.mkdir(exist_ok=True)
    _git(path, "init")
    _git(path, "config", "user.email", "test@test.com")
    _git(path, "config", "user.name", "Test")
    (path / "README.md").write_text("# Initial\n")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "initial")
    return path


@pytest.fixture
def repo(tmp_path):
    """A fresh git repo with one commit on main."""
    return _init_repo(tmp_path / "repo")


@pytest.fixture
def worktree_dir(tmp_path):
    """Directory for worktrees."""
    d = tmp_path / "worktrees"
    d.mkdir()
    return d


@pytest.mark.asyncio
async def test_two_items_have_independent_diffs(repo, worktree_dir):
    """Each item's diff should only contain its own changes."""
    # Create two worktrees with different changes
    wt_a, base_a, commit_a = await create_worktree(repo, worktree_dir, "agent/item-a")
    wt_b, base_b, commit_b = await create_worktree(repo, worktree_dir, "agent/item-b")

    # Item A: create file_a.txt
    (wt_a / "file_a.txt").write_text("content from item A\n")
    _git(wt_a, "add", ".")
    _git(wt_a, "commit", "-m", "item A work")

    # Item B: create file_b.txt
    (wt_b / "file_b.txt").write_text("content from item B\n")
    _git(wt_b, "add", ".")
    _git(wt_b, "commit", "-m", "item B work")

    # Get diffs for both items — using base_commit for stable results
    diff_a = await get_diff(repo, "agent/item-a", base=base_a, worktree_path=wt_a, base_commit=commit_a)
    diff_b = await get_diff(repo, "agent/item-b", base=base_b, worktree_path=wt_b, base_commit=commit_b)

    # Each diff should only contain its own file
    assert "file_a.txt" in diff_a
    assert "file_b.txt" not in diff_a, "Item A's diff contains Item B's file!"

    assert "file_b.txt" in diff_b
    assert "file_a.txt" not in diff_b, "Item B's diff contains Item A's file!"


@pytest.mark.asyncio
async def test_diff_during_concurrent_merge(repo, worktree_dir):
    """Diff for Item A should be stable even while Item B is being merged.

    This tests the race condition: merge_branch() does `git checkout base`
    on the shared repo, which could affect concurrent diff operations.
    """
    # Create two worktrees
    wt_a, base_a, commit_a = await create_worktree(repo, worktree_dir, "agent/item-a")
    wt_b, base_b, commit_b = await create_worktree(repo, worktree_dir, "agent/item-b")

    # Item A: unique change
    (wt_a / "file_a.txt").write_text("item A content\n")
    _git(wt_a, "add", ".")
    _git(wt_a, "commit", "-m", "item A work")

    # Item B: different unique change
    (wt_b / "file_b.txt").write_text("item B content\n")
    _git(wt_b, "add", ".")
    _git(wt_b, "commit", "-m", "item B work")

    # Snapshot Item A's diff BEFORE any merge (using base_commit)
    diff_a_before = await get_diff(repo, "agent/item-a", base=base_a, worktree_path=wt_a, base_commit=commit_a)

    # Now merge Item B (this does `git checkout base` on the shared repo)
    success, msg = await merge_branch(repo, "agent/item-b", base=base_b, worktree_path=wt_b)
    assert success, f"Merge failed: {msg}"

    # Get Item A's diff AFTER Item B was merged into base (using base_commit for stability)
    diff_a_after = await get_diff(repo, "agent/item-a", base=base_a, worktree_path=wt_a, base_commit=commit_a)

    # The diff should still show only Item A's changes
    assert "file_a.txt" in diff_a_after
    assert "item A content" in diff_a_after

    # CRITICAL: After merging B into base, does A's diff now also show B's file?
    # If base has moved forward (now includes B's changes), and we diff base..branch-a,
    # file_b.txt should NOT appear in A's diff (it was never in A's branch).
    # But the diff might LOSE file_b.txt from the "committed" portion since base now has it.
    # The key question: does the diff still accurately represent A's work?
    assert "file_b.txt" not in diff_a_after, (
        "Item A's diff incorrectly includes Item B's file after B was merged!"
    )


@pytest.mark.asyncio
async def test_diff_with_uncommitted_changes_after_merge(repo, worktree_dir):
    """Test that uncommitted worktree changes don't leak between items."""
    wt_a, base_a, commit_a = await create_worktree(repo, worktree_dir, "agent/item-a")
    wt_b, base_b, commit_b = await create_worktree(repo, worktree_dir, "agent/item-b")

    # Item A: committed + uncommitted changes
    (wt_a / "committed_a.txt").write_text("committed by A\n")
    _git(wt_a, "add", ".")
    _git(wt_a, "commit", "-m", "item A committed")
    (wt_a / "uncommitted_a.txt").write_text("uncommitted by A\n")

    # Item B: committed + uncommitted changes
    (wt_b / "committed_b.txt").write_text("committed by B\n")
    _git(wt_b, "add", ".")
    _git(wt_b, "commit", "-m", "item B committed")
    (wt_b / "uncommitted_b.txt").write_text("uncommitted by B\n")

    diff_a = await get_diff(repo, "agent/item-a", base=base_a, worktree_path=wt_a, base_commit=commit_a)
    diff_b = await get_diff(repo, "agent/item-b", base=base_b, worktree_path=wt_b, base_commit=commit_b)

    # A's diff: should have A's files only
    assert "committed_a.txt" in diff_a
    assert "uncommitted_a.txt" in diff_a
    assert "committed_b.txt" not in diff_a
    assert "uncommitted_b.txt" not in diff_a

    # B's diff: should have B's files only
    assert "committed_b.txt" in diff_b
    assert "uncommitted_b.txt" in diff_b
    assert "committed_a.txt" not in diff_b
    assert "uncommitted_a.txt" not in diff_b


@pytest.mark.asyncio
async def test_diff_after_base_moves_forward(repo, worktree_dir):
    """After merging Item B, Item A's diff against the original base should still work.

    This simulates: Item A is in Review, Item B gets approved (merged).
    User then views Item A's diff — what do they see?
    """
    wt_a, base_a, commit_a = await create_worktree(repo, worktree_dir, "agent/item-a")
    wt_b, base_b, commit_b = await create_worktree(repo, worktree_dir, "agent/item-b")

    # Both items modify the SAME file differently
    (wt_a / "shared.txt").write_text("line from item A\n")
    _git(wt_a, "add", ".")
    _git(wt_a, "commit", "-m", "item A changes shared.txt")

    (wt_b / "shared.txt").write_text("line from item B\n")
    _git(wt_b, "add", ".")
    _git(wt_b, "commit", "-m", "item B changes shared.txt")

    # Merge Item B first
    success, _ = await merge_branch(repo, "agent/item-b", base=base_b, worktree_path=wt_b)
    assert success

    # Now get Item A's diff using base_commit (the original SHA, immune to branch moves)
    diff_a = await get_diff(repo, "agent/item-a", base=base_a, worktree_path=wt_a, base_commit=commit_a)

    assert "line from item A" in diff_a, "Item A's own changes should be in the diff"
    # With base_commit fix, the diff is against the original commit SHA,
    # so B's changes (now in main) don't pollute A's diff
    assert "line from item B" not in diff_a, (
        "Item A's diff should not show Item B's changes as removed"
    )


@pytest.mark.asyncio
async def test_concurrent_diff_requests(repo, worktree_dir):
    """Request diffs for multiple items simultaneously."""
    wt_a, base_a, commit_a = await create_worktree(repo, worktree_dir, "agent/item-a")
    wt_b, base_b, commit_b = await create_worktree(repo, worktree_dir, "agent/item-b")

    (wt_a / "only_a.txt").write_text("A content\n")
    _git(wt_a, "add", ".")
    _git(wt_a, "commit", "-m", "A work")

    (wt_b / "only_b.txt").write_text("B content\n")
    _git(wt_b, "add", ".")
    _git(wt_b, "commit", "-m", "B work")

    # Request both diffs concurrently
    diff_a, diff_b = await asyncio.gather(
        get_diff(repo, "agent/item-a", base=base_a, worktree_path=wt_a, base_commit=commit_a),
        get_diff(repo, "agent/item-b", base=base_b, worktree_path=wt_b, base_commit=commit_b),
    )

    assert "only_a.txt" in diff_a
    assert "only_b.txt" not in diff_a

    assert "only_b.txt" in diff_b
    assert "only_a.txt" not in diff_b


@pytest.mark.asyncio
async def test_diff_while_merge_in_progress(repo, worktree_dir):
    """The most dangerous race: request a diff while a merge is actively running.

    merge_branch() calls `git checkout base` on the shared repo.
    If get_diff() runs its `git diff base branch` at the same moment,
    the repo's working state might interfere.
    """
    wt_a, base_a, commit_a = await create_worktree(repo, worktree_dir, "agent/item-a")
    wt_b, base_b, commit_b = await create_worktree(repo, worktree_dir, "agent/item-b")

    (wt_a / "race_a.txt").write_text("A racing content\n")
    _git(wt_a, "add", ".")
    _git(wt_a, "commit", "-m", "A race work")

    (wt_b / "race_b.txt").write_text("B racing content\n")
    _git(wt_b, "add", ".")
    _git(wt_b, "commit", "-m", "B race work")

    # Run merge of B and diff of A concurrently (using base_commit for stable diff)
    merge_result, diff_a = await asyncio.gather(
        merge_branch(repo, "agent/item-b", base=base_b, worktree_path=wt_b),
        get_diff(repo, "agent/item-a", base=base_a, worktree_path=wt_a, base_commit=commit_a),
    )

    success, msg = merge_result
    # The merge might fail due to the race, or succeed
    # Either way, Item A's diff should be correct
    assert "race_a.txt" in diff_a, "Item A's diff should contain its own file"
    assert "race_b.txt" not in diff_a, (
        "Item A's diff contains Item B's file — RACE CONDITION CONFIRMED!"
    )
