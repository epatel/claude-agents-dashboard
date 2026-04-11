"""
Unit tests for src/git/worktree.py
"""
import subprocess
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock, call

from src.git.worktree import create_worktree, remove_worktree, cleanup_worktree, list_worktrees


REPO = Path("/fake/repo")
WORKTREE_DIR = Path("/fake/worktrees")
BRANCH = "feature/my-task"


# ---------------------------------------------------------------------------
# create_worktree — happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_worktree_success():
    """create_worktree returns (path, base_branch, base_commit) on success."""
    with patch("src.git.worktree.get_current_branch", new_callable=AsyncMock) as mock_branch, \
         patch("src.git.worktree.run_git", new_callable=AsyncMock) as mock_git:

        mock_branch.return_value = "main"
        # rev-parse --verify → succeeds (branch exists)
        # rev-parse current  → returns commit SHA
        # worktree add       → succeeds (returns "")
        mock_git.side_effect = [
            "abc1234",   # rev-parse --verify main
            "abc1234",   # rev-parse main  (base_commit)
            "",          # worktree add
        ]

        result = await create_worktree(REPO, WORKTREE_DIR, BRANCH)

    expected_path = WORKTREE_DIR / "feature-my-task"
    assert result == (expected_path, "main", "abc1234")


@pytest.mark.asyncio
async def test_create_worktree_path_uses_sanitized_branch_name():
    """Slashes in branch name are replaced with dashes in the worktree path."""
    with patch("src.git.worktree.get_current_branch", new_callable=AsyncMock) as mock_branch, \
         patch("src.git.worktree.run_git", new_callable=AsyncMock) as mock_git:

        mock_branch.return_value = "main"
        mock_git.side_effect = ["sha", "sha", ""]

        path, _, _ = await create_worktree(REPO, WORKTREE_DIR, "a/b/c")

    assert path == WORKTREE_DIR / "a-b-c"


@pytest.mark.asyncio
async def test_create_worktree_passes_correct_git_args():
    """Verify the exact git commands issued during worktree creation."""
    with patch("src.git.worktree.get_current_branch", new_callable=AsyncMock) as mock_branch, \
         patch("src.git.worktree.run_git", new_callable=AsyncMock) as mock_git:

        mock_branch.return_value = "develop"
        mock_git.side_effect = ["sha999", "sha999", ""]

        await create_worktree(REPO, WORKTREE_DIR, BRANCH)

    expected_worktree_path = str(WORKTREE_DIR / "feature-my-task")
    calls = mock_git.call_args_list
    # First call: verify base branch exists
    assert calls[0] == call(REPO, "rev-parse", "--verify", "develop")
    # Second call: capture base commit SHA
    assert calls[1] == call(REPO, "rev-parse", "develop")
    # Third call: create the worktree
    assert calls[2] == call(
        REPO, "worktree", "add", expected_worktree_path, "-b", BRANCH, "develop"
    )


# ---------------------------------------------------------------------------
# create_worktree — empty repo / no commits
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_worktree_empty_repo_creates_initial_commit(tmp_path):
    """For an empty repo, create_worktree writes a README and commits it."""
    fake_repo = tmp_path / "repo"
    fake_repo.mkdir()
    worktree_dir = tmp_path / "worktrees"

    with patch("src.git.worktree.get_current_branch", new_callable=AsyncMock) as mock_branch, \
         patch("src.git.worktree.run_git", new_callable=AsyncMock) as mock_git:

        mock_branch.return_value = "main"

        def git_side_effect(repo, *args):
            # First call (rev-parse --verify) raises → triggers empty-repo path
            if args == ("rev-parse", "--verify", "main") and not hasattr(git_side_effect, "_verified"):
                git_side_effect._verified = True
                raise subprocess.CalledProcessError(128, "git")
            return "initial_sha"

        mock_git.side_effect = git_side_effect

        result = await create_worktree(fake_repo, worktree_dir, "init-branch")

    # README should have been created on disk
    assert (fake_repo / "README.md").exists()
    # Result tuple should be correct
    assert result[1] == "main"
    assert result[2] == "initial_sha"


@pytest.mark.asyncio
async def test_create_worktree_empty_repo_readme_already_exists(tmp_path):
    """If README.md already exists, skip writing it but still commit."""
    fake_repo = tmp_path / "repo"
    fake_repo.mkdir()
    (fake_repo / "README.md").write_text("existing content\n")
    worktree_dir = tmp_path / "worktrees"

    with patch("src.git.worktree.get_current_branch", new_callable=AsyncMock) as mock_branch, \
         patch("src.git.worktree.run_git", new_callable=AsyncMock) as mock_git:

        mock_branch.return_value = "main"

        called = {"n": 0}

        def git_side_effect(repo, *args):
            called["n"] += 1
            if called["n"] == 1:
                raise subprocess.CalledProcessError(128, "git")
            return "sha_existing"

        mock_git.side_effect = git_side_effect

        result = await create_worktree(fake_repo, worktree_dir, "br")

    # README should be unchanged
    assert (fake_repo / "README.md").read_text() == "existing content\n"
    assert result[2] == "sha_existing"


@pytest.mark.asyncio
async def test_create_worktree_empty_repo_commit_fails_raises_value_error(tmp_path):
    """If the initial commit also fails, ValueError is raised."""
    fake_repo = tmp_path / "repo"
    fake_repo.mkdir()
    worktree_dir = tmp_path / "worktrees"

    with patch("src.git.worktree.get_current_branch", new_callable=AsyncMock) as mock_branch, \
         patch("src.git.worktree.run_git", new_callable=AsyncMock) as mock_git:

        mock_branch.return_value = "main"
        # All git calls fail
        mock_git.side_effect = subprocess.CalledProcessError(128, "git")

        with pytest.raises(ValueError, match="empty"):
            await create_worktree(fake_repo, worktree_dir, "br")


# ---------------------------------------------------------------------------
# remove_worktree
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_remove_worktree_success():
    """remove_worktree calls git worktree remove --force."""
    worktree_path = Path("/fake/worktrees/feature-task")

    with patch("src.git.worktree.run_git", new_callable=AsyncMock) as mock_git:
        mock_git.return_value = ""
        await remove_worktree(REPO, worktree_path)

    mock_git.assert_called_once_with(
        REPO, "worktree", "remove", str(worktree_path), "--force"
    )


@pytest.mark.asyncio
async def test_remove_worktree_propagates_exception():
    """remove_worktree does NOT swallow exceptions."""
    with patch("src.git.worktree.run_git", new_callable=AsyncMock) as mock_git:
        mock_git.side_effect = subprocess.CalledProcessError(1, "git")

        with pytest.raises(subprocess.CalledProcessError):
            await remove_worktree(REPO, Path("/some/path"))


# ---------------------------------------------------------------------------
# cleanup_worktree
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cleanup_worktree_success():
    """cleanup_worktree removes worktree and deletes branch."""
    worktree_path = Path("/fake/worktrees/feature-task")

    with patch("src.git.worktree.run_git", new_callable=AsyncMock) as mock_git:
        mock_git.return_value = ""
        await cleanup_worktree(REPO, worktree_path, BRANCH)

    calls = mock_git.call_args_list
    assert any("worktree" in c.args[1] for c in calls), "worktree remove not called"
    assert any("branch" in c.args[1] for c in calls), "branch delete not called"


@pytest.mark.asyncio
async def test_cleanup_worktree_swallows_remove_error():
    """cleanup_worktree continues if worktree remove fails (already gone)."""
    worktree_path = Path("/fake/worktrees/gone")

    with patch("src.git.worktree.run_git", new_callable=AsyncMock) as mock_git:
        # First call (worktree remove) fails, second (branch -D) succeeds
        mock_git.side_effect = [
            subprocess.CalledProcessError(128, "git"),
            "",
        ]
        # Should not raise
        await cleanup_worktree(REPO, worktree_path, BRANCH)

    assert mock_git.call_count == 2


@pytest.mark.asyncio
async def test_cleanup_worktree_swallows_branch_delete_error():
    """cleanup_worktree completes even if branch delete fails."""
    worktree_path = Path("/fake/worktrees/feature-task")

    with patch("src.git.worktree.run_git", new_callable=AsyncMock) as mock_git:
        mock_git.side_effect = [
            "",  # worktree remove succeeds
            subprocess.CalledProcessError(1, "git"),  # branch -D fails
        ]
        await cleanup_worktree(REPO, worktree_path, BRANCH)

    assert mock_git.call_count == 2


@pytest.mark.asyncio
async def test_cleanup_worktree_both_calls_fail():
    """cleanup_worktree swallows both failures gracefully."""
    with patch("src.git.worktree.run_git", new_callable=AsyncMock) as mock_git:
        mock_git.side_effect = subprocess.CalledProcessError(128, "git")
        # Should not raise
        await cleanup_worktree(REPO, Path("/gone"), "dead-branch")


# ---------------------------------------------------------------------------
# list_worktrees
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_worktrees_parses_porcelain_output():
    """list_worktrees correctly parses multi-entry porcelain output."""
    porcelain = (
        "worktree /repo\n"
        "branch refs/heads/main\n"
        "\n"
        "worktree /repo/worktrees/feature-x\n"
        "branch refs/heads/feature/x\n"
        "\n"
    )

    with patch("src.git.worktree.run_git", new_callable=AsyncMock) as mock_git:
        mock_git.return_value = porcelain.strip()
        result = await list_worktrees(REPO)

    assert len(result) == 2
    assert result[0]["path"] == "/repo"
    assert result[0]["branch"] == "refs/heads/main"
    assert result[1]["path"] == "/repo/worktrees/feature-x"


@pytest.mark.asyncio
async def test_list_worktrees_handles_bare_flag():
    """list_worktrees records bare=True for bare worktrees."""
    porcelain = "worktree /repo\nbare\n"

    with patch("src.git.worktree.run_git", new_callable=AsyncMock) as mock_git:
        mock_git.return_value = porcelain.strip()
        result = await list_worktrees(REPO)

    assert result[0].get("bare") is True


@pytest.mark.asyncio
async def test_list_worktrees_empty_output():
    """list_worktrees returns empty list when there are no worktrees."""
    with patch("src.git.worktree.run_git", new_callable=AsyncMock) as mock_git:
        mock_git.return_value = ""
        result = await list_worktrees(REPO)

    assert result == []
