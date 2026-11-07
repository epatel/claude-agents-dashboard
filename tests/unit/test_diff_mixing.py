"""
Tests to verify whether diffs can get mixed up between items.

The core concern: get_diff() runs `git diff base branch` against the shared
main repo. If another operation (like merge/approve) changes the repo state
concurrently, diffs could be incorrect.
"""
import asyncio
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.git.operations import get_diff, merge_branch
from src.git.worktree import create_worktree


def _git(repo: Path, *args: str) -> str:
    """Synchronous git helper for test setup."""
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


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


@dataclass
class Item:
    """One board item's worktree, as returned by create_worktree()."""

    repo: Path
    branch: str
    wt: Path
    base: str
    commit: str

    def write(self, name: str, content: str) -> None:
        """Write a file into the worktree without committing it."""
        (self.wt / name).write_text(content)

    def commit_file(self, name: str, content: str, message: str) -> None:
        """Write a file into the worktree and commit it on the item branch."""
        self.write(name, content)
        _git(self.wt, "add", ".")
        _git(self.wt, "commit", "-m", message)

    async def diff(self) -> str:
        """The item's diff, pinned to its base_commit for stable results."""
        return await get_diff(
            self.repo, self.branch, base=self.base,
            worktree_path=self.wt, base_commit=self.commit,
        )

    async def merge(self):
        """Merge the item branch into its base on the shared repo."""
        return await merge_branch(
            self.repo, self.branch, base=self.base, worktree_path=self.wt,
        )


@pytest.fixture
def repo(tmp_path):
    """A fresh git repo with one commit on main."""
    return _init_repo(tmp_path / "repo")


@pytest.fixture
async def items(repo, tmp_path):
    """Two items (A and B), each with its own worktree off the same main."""
    worktree_dir = tmp_path / "worktrees"
    worktree_dir.mkdir()
    made = []
    for branch in ("agent/item-a", "agent/item-b"):
        wt, base, commit = await create_worktree(repo, worktree_dir, branch)
        made.append(Item(repo, branch, wt, base, commit))
    return tuple(made)


@pytest.mark.asyncio
async def test_two_items_have_independent_diffs(items):
    """Each item's diff should only contain its own changes."""
    a, b = items
    a.commit_file("file_a.txt", "content from item A\n", "item A work")
    b.commit_file("file_b.txt", "content from item B\n", "item B work")

    diff_a = await a.diff()
    diff_b = await b.diff()

    # Each diff should only contain its own file
    assert "file_a.txt" in diff_a
    assert "file_b.txt" not in diff_a, "Item A's diff contains Item B's file!"

    assert "file_b.txt" in diff_b
    assert "file_a.txt" not in diff_b, "Item B's diff contains Item A's file!"


@pytest.mark.asyncio
async def test_diff_during_concurrent_merge(items):
    """Diff for Item A should be stable even while Item B is being merged.

    This tests the race condition: merge_branch() does `git checkout base`
    on the shared repo, which could affect concurrent diff operations.
    """
    a, b = items
    a.commit_file("file_a.txt", "item A content\n", "item A work")
    b.commit_file("file_b.txt", "item B content\n", "item B work")

    # Snapshot Item A's diff BEFORE any merge (using base_commit)
    await a.diff()

    # Now merge Item B (this does `git checkout base` on the shared repo)
    success, msg = await b.merge()
    assert success, f"Merge failed: {msg}"

    # Get Item A's diff AFTER Item B was merged into base (using base_commit for stability)
    diff_a_after = await a.diff()

    # The diff should still show only Item A's changes
    assert "file_a.txt" in diff_a_after
    assert "item A content" in diff_a_after

    # CRITICAL: After merging B into base, file_b.txt should NOT appear in A's
    # diff (it was never in A's branch).
    assert "file_b.txt" not in diff_a_after, (
        "Item A's diff incorrectly includes Item B's file after B was merged!"
    )


@pytest.mark.asyncio
async def test_diff_with_uncommitted_changes_after_merge(items):
    """Test that uncommitted worktree changes don't leak between items."""
    a, b = items
    # Each item: committed + uncommitted changes
    a.commit_file("committed_a.txt", "committed by A\n", "item A committed")
    a.write("uncommitted_a.txt", "uncommitted by A\n")
    b.commit_file("committed_b.txt", "committed by B\n", "item B committed")
    b.write("uncommitted_b.txt", "uncommitted by B\n")

    diff_a = await a.diff()
    diff_b = await b.diff()

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
async def test_diff_after_base_moves_forward(items):
    """After merging Item B, Item A's diff against the original base should still work.

    This simulates: Item A is in Review, Item B gets approved (merged).
    User then views Item A's diff — what do they see?
    """
    a, b = items
    # Both items modify the SAME file differently
    a.commit_file("shared.txt", "line from item A\n", "item A changes shared.txt")
    b.commit_file("shared.txt", "line from item B\n", "item B changes shared.txt")

    # Merge Item B first
    success, _ = await b.merge()
    assert success

    # Now get Item A's diff using base_commit (the original SHA, immune to branch moves)
    diff_a = await a.diff()

    assert "line from item A" in diff_a, "Item A's own changes should be in the diff"
    # With base_commit fix, the diff is against the original commit SHA,
    # so B's changes (now in main) don't pollute A's diff
    assert "line from item B" not in diff_a, (
        "Item A's diff should not show Item B's changes as removed"
    )


@pytest.mark.asyncio
async def test_concurrent_diff_requests(items):
    """Request diffs for multiple items simultaneously."""
    a, b = items
    a.commit_file("only_a.txt", "A content\n", "A work")
    b.commit_file("only_b.txt", "B content\n", "B work")

    # Request both diffs concurrently
    diff_a, diff_b = await asyncio.gather(a.diff(), b.diff())

    assert "only_a.txt" in diff_a
    assert "only_b.txt" not in diff_a

    assert "only_b.txt" in diff_b
    assert "only_a.txt" not in diff_b


@pytest.mark.asyncio
async def test_diff_while_merge_in_progress(items):
    """The most dangerous race: request a diff while a merge is actively running.

    merge_branch() calls `git checkout base` on the shared repo.
    If get_diff() runs its `git diff base branch` at the same moment,
    the repo's working state might interfere.
    """
    a, b = items
    a.commit_file("race_a.txt", "A racing content\n", "A race work")
    b.commit_file("race_b.txt", "B racing content\n", "B race work")

    # Run merge of B and diff of A concurrently (using base_commit for stable diff)
    _merge_result, diff_a = await asyncio.gather(b.merge(), a.diff())

    # The merge might fail due to the race, or succeed
    # Either way, Item A's diff should be correct
    assert "race_a.txt" in diff_a, "Item A's diff should contain its own file"
    assert "race_b.txt" not in diff_a, (
        "Item A's diff contains Item B's file — RACE CONDITION CONFIRMED!"
    )
