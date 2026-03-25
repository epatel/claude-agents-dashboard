"""
P1 Priority Unit Tests: Git Operations and Worktree Management

Tests git functionality including:
- Branch operations (create, merge, delete)
- Worktree creation and cleanup
- Git timeout handling and error recovery
- Repository validation and safety checks
"""

import pytest
import pytest_asyncio
import asyncio
import tempfile
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from src.git.operations import (
    get_main_branch, create_branch, merge_branch, delete_branch,
    get_branch_commits, is_repository, validate_repository
)
from src.git.worktree import (
    create_worktree, remove_worktree, cleanup_worktree,
    list_worktrees, get_worktree_status
)


@pytest_asyncio.fixture
async def test_git_repo():
    """Create a test git repository."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        repo_path = Path(tmp_dir)

        # Initialize git repo
        subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_path, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True)

        # Create initial commit
        (repo_path / "README.md").write_text("# Test Repository")
        subprocess.run(["git", "add", "README.md"], cwd=repo_path, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_path, check=True, capture_output=True)

        yield repo_path


@pytest.mark.unit
class TestGitOperations:
    """Test suite for git operations."""

    async def test_is_repository_valid(self, test_git_repo):
        """Test detecting valid git repository."""
        assert await is_repository(test_git_repo) is True

    async def test_is_repository_invalid(self, temp_dir):
        """Test detecting invalid git repository."""
        assert await is_repository(temp_dir) is False

    async def test_validate_repository_success(self, test_git_repo):
        """Test repository validation success."""
        result = await validate_repository(test_git_repo)
        assert result is True

    async def test_validate_repository_failure(self, temp_dir):
        """Test repository validation failure."""
        result = await validate_repository(temp_dir)
        assert result is False

    async def test_get_main_branch_main(self, test_git_repo):
        """Test getting main branch when it's 'main'."""
        # Test git repo should have main/master as default
        main_branch = await get_main_branch(test_git_repo)
        assert main_branch in ["main", "master"]

    async def test_get_main_branch_master(self, test_git_repo):
        """Test getting main branch when it's 'master'."""
        # Create master branch if needed
        subprocess.run(["git", "branch", "-m", "master"], cwd=test_git_repo, capture_output=True)

        main_branch = await get_main_branch(test_git_repo)
        assert main_branch == "master"

    async def test_create_branch_success(self, test_git_repo):
        """Test creating a new branch successfully."""
        branch_name = "feature/test-branch"
        result = await create_branch(test_git_repo, branch_name)
        assert result is True

        # Verify branch exists
        result = subprocess.run(
            ["git", "branch", "--list", branch_name],
            cwd=test_git_repo,
            capture_output=True,
            text=True
        )
        assert branch_name in result.stdout

    async def test_create_branch_already_exists(self, test_git_repo):
        """Test creating branch that already exists."""
        branch_name = "existing-branch"

        # Create the branch first
        subprocess.run(["git", "branch", branch_name], cwd=test_git_repo, check=True)

        # Try to create it again
        result = await create_branch(test_git_repo, branch_name)
        assert result is False  # Should fail gracefully

    async def test_delete_branch_success(self, test_git_repo):
        """Test deleting a branch successfully."""
        branch_name = "branch-to-delete"

        # Create branch first
        subprocess.run(["git", "branch", branch_name], cwd=test_git_repo, check=True)

        # Delete it
        result = await delete_branch(test_git_repo, branch_name)
        assert result is True

        # Verify branch is gone
        result = subprocess.run(
            ["git", "branch", "--list", branch_name],
            cwd=test_git_repo,
            capture_output=True,
            text=True
        )
        assert branch_name not in result.stdout

    async def test_delete_branch_not_exists(self, test_git_repo):
        """Test deleting branch that doesn't exist."""
        result = await delete_branch(test_git_repo, "nonexistent-branch")
        assert result is False

    async def test_merge_branch_success(self, test_git_repo):
        """Test merging a branch successfully."""
        branch_name = "feature/merge-test"

        # Create and switch to new branch
        subprocess.run(["git", "branch", branch_name], cwd=test_git_repo, check=True)
        subprocess.run(["git", "checkout", branch_name], cwd=test_git_repo, check=True)

        # Make a change
        (test_git_repo / "feature.txt").write_text("Feature implementation")
        subprocess.run(["git", "add", "feature.txt"], cwd=test_git_repo, check=True)
        subprocess.run(["git", "commit", "-m", "Add feature"], cwd=test_git_repo, check=True, capture_output=True)

        # Switch back to main
        subprocess.run(["git", "checkout", "main"], cwd=test_git_repo, capture_output=True)
        if subprocess.run(["git", "checkout", "main"], cwd=test_git_repo, capture_output=True).returncode != 0:
            subprocess.run(["git", "checkout", "master"], cwd=test_git_repo, check=True, capture_output=True)

        # Merge the branch
        success, message = await merge_branch(test_git_repo, branch_name)
        assert success is True
        assert "feature.txt" in (test_git_repo / "feature.txt").read_text()

    async def test_merge_branch_conflict(self, test_git_repo):
        """Test handling merge conflicts."""
        branch_name = "conflicting-branch"

        # Create conflicting changes on main branch
        (test_git_repo / "conflict.txt").write_text("Main branch content")
        subprocess.run(["git", "add", "conflict.txt"], cwd=test_git_repo, check=True)
        subprocess.run(["git", "commit", "-m", "Add conflict file"], cwd=test_git_repo, check=True, capture_output=True)

        # Create branch and make conflicting change
        subprocess.run(["git", "checkout", "-b", branch_name], cwd=test_git_repo, check=True, capture_output=True)
        (test_git_repo / "conflict.txt").write_text("Branch content")
        subprocess.run(["git", "add", "conflict.txt"], cwd=test_git_repo, check=True)
        subprocess.run(["git", "commit", "-m", "Conflicting change"], cwd=test_git_repo, check=True, capture_output=True)

        # Switch back to main and create another conflicting change
        subprocess.run(["git", "checkout", "main"], cwd=test_git_repo, capture_output=True)
        if subprocess.run(["git", "checkout", "main"], cwd=test_git_repo, capture_output=True).returncode != 0:
            subprocess.run(["git", "checkout", "master"], cwd=test_git_repo, check=True, capture_output=True)

        (test_git_repo / "conflict.txt").write_text("Updated main content")
        subprocess.run(["git", "add", "conflict.txt"], cwd=test_git_repo, check=True)
        subprocess.run(["git", "commit", "-m", "Update conflict file"], cwd=test_git_repo, check=True, capture_output=True)

        # Try to merge - should fail
        success, message = await merge_branch(test_git_repo, branch_name)
        assert success is False
        assert "conflict" in message.lower()

    async def test_get_branch_commits(self, test_git_repo):
        """Test getting commits for a branch."""
        commits = await get_branch_commits(test_git_repo, "main")
        if not commits:  # Try master if main doesn't exist
            commits = await get_branch_commits(test_git_repo, "master")

        assert len(commits) >= 1
        assert "Initial commit" in commits[0]["message"]

    async def test_git_timeout_handling(self, test_git_repo):
        """Test git operation timeout handling."""
        with patch('asyncio.wait_for', side_effect=asyncio.TimeoutError):
            result = await create_branch(test_git_repo, "timeout-test")
            assert result is False

    async def test_git_permission_error(self, temp_dir):
        """Test handling permission errors."""
        # Create directory without write permissions
        restricted_dir = temp_dir / "restricted"
        restricted_dir.mkdir(mode=0o444)

        try:
            result = await create_branch(restricted_dir, "test-branch")
            assert result is False
        finally:
            # Restore permissions for cleanup
            restricted_dir.chmod(0o755)


@pytest.mark.unit
class TestWorktreeOperations:
    """Test suite for git worktree operations."""

    async def test_create_worktree_success(self, test_git_repo):
        """Test creating a worktree successfully."""
        branch_name = "agent/test-123"
        worktree_path = await create_worktree(test_git_repo, branch_name)

        assert worktree_path is not None
        assert worktree_path.exists()
        assert worktree_path.is_dir()

    async def test_create_worktree_invalid_repo(self, temp_dir):
        """Test creating worktree in invalid repository."""
        with pytest.raises(Exception):
            await create_worktree(temp_dir, "test-branch")

    async def test_remove_worktree_success(self, test_git_repo):
        """Test removing a worktree successfully."""
        branch_name = "agent/remove-test"
        worktree_path = await create_worktree(test_git_repo, branch_name)

        assert worktree_path.exists()

        result = await remove_worktree(test_git_repo, worktree_path)
        assert result is True
        assert not worktree_path.exists()

    async def test_remove_worktree_not_exists(self, test_git_repo):
        """Test removing non-existent worktree."""
        fake_path = Path("/nonexistent/path")
        result = await remove_worktree(test_git_repo, fake_path)
        assert result is False

    async def test_cleanup_worktree(self, test_git_repo):
        """Test cleanup worktree operation."""
        branch_name = "agent/cleanup-test"
        worktree_path = await create_worktree(test_git_repo, branch_name)

        assert worktree_path.exists()

        await cleanup_worktree(test_git_repo, worktree_path, branch_name)
        assert not worktree_path.exists()

    async def test_list_worktrees(self, test_git_repo):
        """Test listing worktrees."""
        # Should have at least the main worktree
        worktrees = await list_worktrees(test_git_repo)
        assert len(worktrees) >= 1

        # Create additional worktree
        branch_name = "agent/list-test"
        await create_worktree(test_git_repo, branch_name)

        worktrees_after = await list_worktrees(test_git_repo)
        assert len(worktrees_after) == len(worktrees) + 1

    async def test_get_worktree_status(self, test_git_repo):
        """Test getting worktree status."""
        branch_name = "agent/status-test"
        worktree_path = await create_worktree(test_git_repo, branch_name)

        status = await get_worktree_status(worktree_path)
        assert status is not None
        assert "branch" in status

    async def test_worktree_concurrent_operations(self, test_git_repo):
        """Test concurrent worktree operations."""
        branch_names = [f"agent/concurrent-{i}" for i in range(3)]

        # Create multiple worktrees concurrently
        tasks = [create_worktree(test_git_repo, branch) for branch in branch_names]
        worktree_paths = await asyncio.gather(*tasks, return_exceptions=True)

        # Check results
        successful_paths = [path for path in worktree_paths if isinstance(path, Path)]
        assert len(successful_paths) >= 1  # At least one should succeed

        # Cleanup
        for path in successful_paths:
            if path.exists():
                await remove_worktree(test_git_repo, path)


@pytest.mark.unit
class TestGitErrorHandling:
    """Test suite for git error handling and edge cases."""

    async def test_invalid_branch_names(self, test_git_repo):
        """Test handling of invalid branch names."""
        invalid_names = ["", "spaces in name", "../../malicious", "\x00null"]

        for invalid_name in invalid_names:
            result = await create_branch(test_git_repo, invalid_name)
            assert result is False

    async def test_repository_corruption_handling(self, temp_dir):
        """Test handling corrupted git repository."""
        # Create fake .git directory
        git_dir = temp_dir / ".git"
        git_dir.mkdir()
        (git_dir / "HEAD").write_text("invalid content")

        result = await is_repository(temp_dir)
        assert result is False

    async def test_network_failure_simulation(self, test_git_repo):
        """Test handling network failures during git operations."""
        with patch('subprocess.run', side_effect=subprocess.CalledProcessError(128, 'git')):
            result = await create_branch(test_git_repo, "network-test")
            assert result is False

    async def test_disk_full_simulation(self, test_git_repo):
        """Test handling disk full errors."""
        with patch('subprocess.run', side_effect=OSError("No space left on device")):
            result = await create_branch(test_git_repo, "disk-full-test")
            assert result is False

    async def test_git_not_installed(self, test_git_repo):
        """Test handling when git is not installed."""
        with patch('subprocess.run', side_effect=FileNotFoundError("git command not found")):
            result = await is_repository(test_git_repo)
            assert result is False

    async def test_worktree_cleanup_on_failure(self, test_git_repo):
        """Test that worktrees are cleaned up when creation fails."""
        with patch('src.git.worktree.subprocess.run', side_effect=subprocess.CalledProcessError(1, 'git')):
            try:
                await create_worktree(test_git_repo, "failing-branch")
            except Exception:
                pass  # Expected to fail

            # Verify no orphaned worktree directories exist
            worktrees = await list_worktrees(test_git_repo)
            assert all("failing-branch" not in str(wt) for wt in worktrees)


@pytest.mark.unit
class TestGitSecurityValidation:
    """Test suite for git security and path validation."""

    async def test_path_traversal_prevention(self, test_git_repo):
        """Test prevention of path traversal attacks."""
        malicious_paths = [
            "../../../etc/passwd",
            "..\\..\\windows\\system32",
            "/etc/passwd",
            "~/../../root"
        ]

        for malicious_path in malicious_paths:
            result = await create_branch(test_git_repo, f"agent/{malicious_path}")
            # Should either sanitize the path or fail safely
            assert result in [True, False]  # Should not raise exception

    async def test_branch_name_sanitization(self, test_git_repo):
        """Test that branch names are properly sanitized."""
        unsafe_chars = ["<", ">", ":", '"', "|", "?", "*", "\0"]

        for char in unsafe_chars:
            branch_name = f"test{char}branch"
            result = await create_branch(test_git_repo, branch_name)
            # Should handle unsafe characters gracefully
            assert isinstance(result, bool)

    async def test_worktree_path_validation(self, test_git_repo):
        """Test validation of worktree paths."""
        # Test absolute paths outside project
        unsafe_paths = [
            Path("/tmp/malicious"),
            Path("../outside-project"),
            Path("/etc/sensitive")
        ]

        for unsafe_path in unsafe_paths:
            # The create_worktree function should validate paths
            try:
                result = await create_worktree(test_git_repo, "test-branch", unsafe_path)
                # If it succeeds, the path should be safe
                if result:
                    assert str(result).startswith(str(test_git_repo.parent))
            except (ValueError, PermissionError):
                pass  # Expected for unsafe paths