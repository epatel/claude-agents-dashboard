"""
Tests for git operation timeout handling.
"""
import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from src.git.operations import run_git, merge_branch
from src.config import GIT_OPERATION_TIMEOUT, GIT_MERGE_TIMEOUT


@pytest.mark.asyncio
async def test_run_git_timeout():
    """Test that run_git respects timeout parameter."""
    # Create a mock process that never finishes
    mock_proc = MagicMock()
    mock_proc.returncode = None
    mock_proc.communicate = AsyncMock()
    mock_proc.communicate.side_effect = asyncio.TimeoutError()
    mock_proc.terminate = MagicMock()
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock()

    with patch('asyncio.create_subprocess_exec', return_value=mock_proc):
        with pytest.raises(asyncio.TimeoutError, match="Git command timed out"):
            await run_git(Path("/fake/repo"), "status", timeout=0.1)

        # Verify process cleanup was attempted
        mock_proc.terminate.assert_called_once()


@pytest.mark.asyncio
async def test_run_git_uses_merge_timeout_for_merge():
    """Test that merge operations get longer timeout by default."""
    with patch('asyncio.create_subprocess_exec') as mock_create:
        with patch('asyncio.wait_for') as mock_wait_for:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"success", b""))
            mock_create.return_value = mock_proc
            mock_wait_for.return_value = (b"success", b"")

            await run_git(Path("/fake/repo"), "merge", "feature-branch")

            # Verify wait_for was called with merge timeout
            mock_wait_for.assert_called_once()
            timeout_arg = mock_wait_for.call_args[1]['timeout']
            assert timeout_arg == GIT_MERGE_TIMEOUT


@pytest.mark.asyncio
async def test_run_git_uses_default_timeout_for_other_operations():
    """Test that non-merge operations get standard timeout."""
    with patch('asyncio.create_subprocess_exec') as mock_create:
        with patch('asyncio.wait_for') as mock_wait_for:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"success", b""))
            mock_create.return_value = mock_proc
            mock_wait_for.return_value = (b"success", b"")

            await run_git(Path("/fake/repo"), "status")

            # Verify wait_for was called with default timeout
            mock_wait_for.assert_called_once()
            timeout_arg = mock_wait_for.call_args[1]['timeout']
            assert timeout_arg == GIT_OPERATION_TIMEOUT


@pytest.mark.asyncio
async def test_merge_branch_handles_timeout():
    """Test that merge_branch propagates timeout errors."""
    with patch('src.git.operations.get_current_branch', return_value="main"):
        with patch('src.git.operations.run_git') as mock_run_git:
            # status --porcelain (clean), checkout succeeds, merge times out, abort succeeds
            mock_run_git.side_effect = ["", None, asyncio.TimeoutError("Merge timed out"), None]

            success, message = await merge_branch(Path("/fake/repo"), "feature-branch")

            assert success is False
            assert "timed out" in message.lower()


@pytest.mark.asyncio
async def test_merge_branch_aborts_on_timeout():
    """Test that merge_branch calls merge --abort when timeout occurs."""
    with patch('src.git.operations.get_current_branch', return_value="main"):
        with patch('src.git.operations.run_git') as mock_run_git:
            # status --porcelain (clean), checkout succeeds, merge times out, abort succeeds
            mock_run_git.side_effect = [
                "",    # status --porcelain
                None,  # checkout
                asyncio.TimeoutError("Merge timed out"),  # merge
                None   # abort
            ]

            success, message = await merge_branch(Path("/fake/repo"), "feature-branch")

            assert success is False
            # Verify abort was called
            abort_call = [call for call in mock_run_git.call_args_list if 'abort' in str(call)]
            assert len(abort_call) == 1