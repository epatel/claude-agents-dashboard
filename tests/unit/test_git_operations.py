"""
Unit tests for src/git/operations.py.

Covers: run_git success/failure, get_main_branch, get_current_branch,
get_diff (no worktree path), get_changed_files, validate_file_path,
get_file_content, rebase_branch, commit_worktree_changes, merge_branch.

Does NOT duplicate tests already in:
  - test_git_timeout.py   (run_git timeout, merge timeout/abort)
  - test_diff_mixing.py   (get_diff/get_changed_files with real worktrees)
"""
import asyncio
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from src.git.operations import (
    run_git,
    get_main_branch,
    get_current_branch,
    get_diff,
    get_changed_files,
    validate_file_path,
    get_file_content,
    rebase_branch,
    commit_worktree_changes,
    merge_branch,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_proc(stdout=b"", stderr=b"", returncode=0):
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    return proc


REPO = Path("/fake/repo")


# ---------------------------------------------------------------------------
# run_git — success / failure (timeouts covered in test_git_timeout.py)
# ---------------------------------------------------------------------------

class TestRunGit:
    @pytest.mark.asyncio
    async def test_success_returns_stripped_stdout(self):
        proc = _mock_proc(stdout=b"  main\n")
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await run_git(REPO, "rev-parse", "--abbrev-ref", "HEAD")
        assert result == "main"

    @pytest.mark.asyncio
    async def test_nonzero_returncode_raises_called_process_error(self):
        proc = _mock_proc(stdout=b"", stderr=b"fatal: not a repo", returncode=128)
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            with pytest.raises(subprocess.CalledProcessError) as exc_info:
                await run_git(REPO, "status")
        assert exc_info.value.returncode == 128

    @pytest.mark.asyncio
    async def test_explicit_timeout_passed_to_wait_for(self):
        proc = _mock_proc(stdout=b"ok")
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            with patch("asyncio.wait_for", return_value=(b"ok", b"")) as mock_wf:
                proc.returncode = 0
                await run_git(REPO, "status", timeout=42.0)
                mock_wf.assert_called_once()
                assert mock_wf.call_args[1]["timeout"] == 42.0

    @pytest.mark.asyncio
    async def test_cwd_passed_to_subprocess(self):
        proc = _mock_proc(stdout=b"x")
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await run_git(REPO, "log")
        mock_exec.assert_called_once()
        assert mock_exec.call_args[1]["cwd"] == str(REPO)

    @pytest.mark.asyncio
    async def test_git_is_first_arg(self):
        proc = _mock_proc(stdout=b"x")
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await run_git(REPO, "status")
        args = mock_exec.call_args[0]
        assert args[0] == "git"
        assert "status" in args


# ---------------------------------------------------------------------------
# get_main_branch
# ---------------------------------------------------------------------------

class TestGetMainBranch:
    @pytest.mark.asyncio
    async def test_returns_main_when_main_exists(self):
        async def _run_git_side_effect(cwd, *args, **kwargs):
            if args == ("rev-parse", "--verify", "main"):
                return "abc123"
            raise AssertionError(f"Unexpected call: {args}")

        with patch("src.git.operations.run_git", side_effect=_run_git_side_effect):
            result = await get_main_branch(REPO)
        assert result == "main"

    @pytest.mark.asyncio
    async def test_returns_master_when_main_missing(self):
        async def _run_git_side_effect(cwd, *args, **kwargs):
            if args == ("rev-parse", "--verify", "main"):
                raise subprocess.CalledProcessError(128, "git")
            if args == ("rev-parse", "--verify", "master"):
                return "def456"
            raise AssertionError(f"Unexpected call: {args}")

        with patch("src.git.operations.run_git", side_effect=_run_git_side_effect):
            result = await get_main_branch(REPO)
        assert result == "master"

    @pytest.mark.asyncio
    async def test_falls_back_to_current_branch_when_neither_exists(self):
        async def _run_git_side_effect(cwd, *args, **kwargs):
            if args[0] == "rev-parse" and args[-1] in ("main", "master"):
                raise subprocess.CalledProcessError(128, "git")
            raise AssertionError(f"Unexpected call: {args}")

        with patch("src.git.operations.run_git", side_effect=_run_git_side_effect):
            with patch("src.git.operations.get_current_branch", return_value="develop") as mock_gcb:
                result = await get_main_branch(REPO)
        assert result == "develop"
        mock_gcb.assert_called_once_with(REPO)


# ---------------------------------------------------------------------------
# get_current_branch
# ---------------------------------------------------------------------------

class TestGetCurrentBranch:
    @pytest.mark.asyncio
    async def test_returns_branch_name(self):
        with patch("src.git.operations.run_git", return_value="feature/foo"):
            result = await get_current_branch(REPO)
        assert result == "feature/foo"

    @pytest.mark.asyncio
    async def test_falls_back_to_symbolic_ref_on_error(self):
        call_count = 0

        async def _side_effect(cwd, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise subprocess.CalledProcessError(128, "git")
            return "unborn"

        with patch("src.git.operations.run_git", side_effect=_side_effect):
            result = await get_current_branch(REPO)
        assert result == "unborn"

    @pytest.mark.asyncio
    async def test_returns_main_when_both_fail(self):
        async def _side_effect(cwd, *args, **kwargs):
            raise subprocess.CalledProcessError(128, "git")

        with patch("src.git.operations.run_git", side_effect=_side_effect):
            result = await get_current_branch(REPO)
        assert result == "main"


# ---------------------------------------------------------------------------
# get_diff — no worktree path (simple branch diff)
# ---------------------------------------------------------------------------

class TestGetDiffSimple:
    @pytest.mark.asyncio
    async def test_no_worktree_calls_run_git_diff(self):
        with patch("src.git.operations.run_git", return_value="diff output") as mock_rg:
            result = await get_diff(REPO, "feature", base="main")
        assert result == "diff output"
        mock_rg.assert_called_once_with(REPO, "diff", "main", "feature")

    @pytest.mark.asyncio
    async def test_no_base_resolves_main_branch(self):
        with patch("src.git.operations.get_main_branch", return_value="master") as mock_gmb:
            with patch("src.git.operations.run_git", return_value="diff") as mock_rg:
                await get_diff(REPO, "feature")
        mock_gmb.assert_called_once_with(REPO)
        mock_rg.assert_called_once_with(REPO, "diff", "master", "feature")

    @pytest.mark.asyncio
    async def test_base_commit_takes_precedence_over_base(self):
        with patch("src.git.operations.run_git", return_value="diff") as mock_rg:
            await get_diff(REPO, "feature", base="main", base_commit="abc123sha")
        mock_rg.assert_called_once_with(REPO, "diff", "abc123sha", "feature")

    @pytest.mark.asyncio
    async def test_worktree_path_not_exists_falls_back_to_simple_diff(self, tmp_path):
        nonexistent = tmp_path / "no_such_worktree"
        with patch("src.git.operations.run_git", return_value="fallback diff") as mock_rg:
            result = await get_diff(REPO, "feature", base="main", worktree_path=nonexistent)
        assert result == "fallback diff"
        mock_rg.assert_called_once_with(REPO, "diff", "main", "feature")


# ---------------------------------------------------------------------------
# get_diff — with existing worktree path
# ---------------------------------------------------------------------------

class TestGetDiffWithWorktree:
    @pytest.mark.asyncio
    async def test_combines_committed_and_uncommitted_changes(self, tmp_path):
        worktree = tmp_path / "wt"
        worktree.mkdir()

        async def _run_git_side(cwd, *args, **kwargs):
            if args == ("diff", "main", "feature"):
                return "committed diff"
            if args == ("diff", "HEAD"):
                return "uncommitted diff"
            if args == ("ls-files", "--others", "--exclude-standard"):
                return ""
            return ""

        with patch("src.git.operations.run_git", side_effect=_run_git_side):
            result = await get_diff(REPO, "feature", base="main", worktree_path=worktree)

        assert "committed diff" in result
        assert "uncommitted diff" in result

    @pytest.mark.asyncio
    async def test_includes_untracked_file_in_diff(self, tmp_path):
        worktree = tmp_path / "wt"
        worktree.mkdir()
        new_file = worktree / "new.txt"
        new_file.write_text("hello\nworld")

        async def _run_git_side(cwd, *args, **kwargs):
            if args[0] == "diff" and len(args) == 3:
                return ""
            if args == ("diff", "HEAD"):
                return ""
            if args == ("ls-files", "--others", "--exclude-standard"):
                return "new.txt"
            return ""

        with patch("src.git.operations.run_git", side_effect=_run_git_side):
            result = await get_diff(REPO, "feature", base="main", worktree_path=worktree)

        assert "new.txt" in result
        assert "+hello" in result

    @pytest.mark.asyncio
    async def test_skips_traversal_untracked_files(self, tmp_path):
        worktree = tmp_path / "wt"
        worktree.mkdir()

        async def _run_git_side(cwd, *args, **kwargs):
            if args[0] == "diff":
                return ""
            if args == ("ls-files", "--others", "--exclude-standard"):
                return "../escape.txt"
            return ""

        with patch("src.git.operations.run_git", side_effect=_run_git_side):
            result = await get_diff(REPO, "feature", base="main", worktree_path=worktree)

        assert "escape.txt" not in result

    @pytest.mark.asyncio
    async def test_committed_diff_error_is_swallowed(self, tmp_path):
        worktree = tmp_path / "wt"
        worktree.mkdir()

        async def _run_git_side(cwd, *args, **kwargs):
            if args[0] == "diff" and len(args) == 3:
                raise subprocess.CalledProcessError(1, "git")
            if args == ("diff", "HEAD"):
                return "uncommitted only"
            if args == ("ls-files", "--others", "--exclude-standard"):
                return ""
            return ""

        with patch("src.git.operations.run_git", side_effect=_run_git_side):
            result = await get_diff(REPO, "feature", base="main", worktree_path=worktree)

        assert "uncommitted only" in result


# ---------------------------------------------------------------------------
# get_changed_files
# ---------------------------------------------------------------------------

class TestGetChangedFiles:
    @pytest.mark.asyncio
    async def test_parses_name_status_output(self):
        with patch("src.git.operations.run_git", return_value="M\tsrc/foo.py\nA\tsrc/bar.py"):
            result = await get_changed_files(REPO, "feature", base="main")

        paths = [f["path"] for f in result]
        assert "src/foo.py" in paths
        assert "src/bar.py" in paths

    @pytest.mark.asyncio
    async def test_status_labels_mapped_correctly(self):
        with patch("src.git.operations.run_git", return_value="D\told.py"):
            result = await get_changed_files(REPO, "feature", base="main")
        assert result[0]["status"] == "D"
        assert result[0]["status_label"] == "Deleted"

    @pytest.mark.asyncio
    async def test_renamed_file_status_label(self):
        with patch("src.git.operations.run_git", return_value="R\tnew.py"):
            result = await get_changed_files(REPO, "feature", base="main")
        assert result[0]["status_label"] == "Renamed"

    @pytest.mark.asyncio
    async def test_unknown_status_code_used_as_label(self):
        with patch("src.git.operations.run_git", return_value="X\tfile.py"):
            result = await get_changed_files(REPO, "feature", base="main")
        assert result[0]["status_label"] == "X"

    @pytest.mark.asyncio
    async def test_empty_output_returns_empty_list(self):
        with patch("src.git.operations.run_git", return_value=""):
            result = await get_changed_files(REPO, "feature", base="main")
        assert result == []

    @pytest.mark.asyncio
    async def test_git_error_returns_empty_list(self):
        with patch("src.git.operations.run_git", side_effect=subprocess.CalledProcessError(1, "git")):
            result = await get_changed_files(REPO, "feature", base="main")
        assert result == []

    @pytest.mark.asyncio
    async def test_no_base_resolves_main_branch(self):
        with patch("src.git.operations.get_main_branch", return_value="master") as mock_gmb:
            with patch("src.git.operations.run_git", return_value=""):
                await get_changed_files(REPO, "feature")
        mock_gmb.assert_called_once_with(REPO)

    @pytest.mark.asyncio
    async def test_base_commit_takes_precedence(self):
        with patch("src.git.operations.run_git", return_value="M\tfoo.py") as mock_rg:
            await get_changed_files(REPO, "feature", base="main", base_commit="deadbeef")
        first_call_args = mock_rg.call_args_list[0][0]
        assert "deadbeef" in first_call_args

    @pytest.mark.asyncio
    async def test_worktree_uncommitted_changes_included(self, tmp_path):
        worktree = tmp_path / "wt"
        worktree.mkdir()

        call_count = 0

        async def _run_git_side(cwd, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if args[:2] == ("diff", "--name-status") and len(args) == 4:
                return "M\tbase_file.py"
            if args == ("diff", "--name-status", "HEAD"):
                return "M\tworktree_file.py"
            if args == ("ls-files", "--others", "--exclude-standard"):
                return ""
            return ""

        with patch("src.git.operations.run_git", side_effect=_run_git_side):
            result = await get_changed_files(REPO, "feature", base="main", worktree_path=worktree)

        paths = [f["path"] for f in result]
        assert "base_file.py" in paths
        assert "worktree_file.py" in paths

    @pytest.mark.asyncio
    async def test_untracked_in_worktree_added_as_A(self, tmp_path):
        worktree = tmp_path / "wt"
        worktree.mkdir()
        (worktree / "new.py").write_text("x")

        async def _run_git_side(cwd, *args, **kwargs):
            if args[:2] == ("diff", "--name-status"):
                return ""
            if args == ("ls-files", "--others", "--exclude-standard"):
                return "new.py"
            return ""

        with patch("src.git.operations.run_git", side_effect=_run_git_side):
            result = await get_changed_files(REPO, "feature", base="main", worktree_path=worktree)

        assert any(f["path"] == "new.py" and f["status"] == "A" for f in result)

    @pytest.mark.asyncio
    async def test_traversal_untracked_file_skipped(self, tmp_path):
        worktree = tmp_path / "wt"
        worktree.mkdir()

        async def _run_git_side(cwd, *args, **kwargs):
            if args[:2] == ("diff", "--name-status"):
                return ""
            if args == ("ls-files", "--others", "--exclude-standard"):
                return "../outside.py"
            return ""

        with patch("src.git.operations.run_git", side_effect=_run_git_side):
            result = await get_changed_files(REPO, "feature", base="main", worktree_path=worktree)

        assert not any("outside" in f["path"] for f in result)

    @pytest.mark.asyncio
    async def test_results_sorted_by_path(self):
        with patch("src.git.operations.run_git", return_value="M\tz.py\nM\ta.py\nM\tm.py"):
            result = await get_changed_files(REPO, "feature", base="main")
        paths = [f["path"] for f in result]
        assert paths == sorted(paths)


# ---------------------------------------------------------------------------
# validate_file_path
# ---------------------------------------------------------------------------

class TestValidateFilePath:
    def test_valid_path_returns_normalized(self):
        result = validate_file_path("src/foo.py")
        assert result == "src/foo.py"

    def test_empty_path_raises(self):
        with pytest.raises(ValueError, match="empty"):
            validate_file_path("")

    def test_absolute_path_raises(self):
        with pytest.raises(ValueError, match="Absolute"):
            validate_file_path("/etc/passwd")

    def test_parent_traversal_raises(self):
        with pytest.raises(ValueError, match="traversal"):
            validate_file_path("../../etc/passwd")

    def test_traversal_in_middle_raises(self):
        with pytest.raises(ValueError, match="traversal"):
            validate_file_path("src/../../../etc/shadow")

    def test_null_byte_stripped_from_valid_path(self):
        # Null bytes are stripped; the remaining path is valid
        result = validate_file_path("\x00src/foo.py")
        assert result == "src/foo.py"

    def test_pure_null_byte_normalizes_to_dot(self):
        # "\x00" passes the empty check (truthy), gets stripped to "",
        # os.path.normpath("") returns "." which is valid (current dir)
        result = validate_file_path("\x00")
        assert result == "."

    def test_tilde_home_expansion_raises(self):
        with pytest.raises(ValueError, match="~/"):
            validate_file_path("~/secret")

    def test_double_slash_raises(self):
        with pytest.raises(ValueError, match="//"):
            validate_file_path("src//file.py")

    def test_backslash_raises(self):
        with pytest.raises(ValueError, match="\\\\"):
            validate_file_path("src\\file.py")

    def test_newline_in_path_raises(self):
        with pytest.raises(ValueError):
            validate_file_path("src/file\n.py")

    def test_carriage_return_raises(self):
        with pytest.raises(ValueError):
            validate_file_path("src/file\r.py")

    def test_plain_filename_valid(self):
        result = validate_file_path("README.md")
        assert result == "README.md"

    def test_nested_path_valid(self):
        result = validate_file_path("a/b/c/d.txt")
        assert result == "a/b/c/d.txt"

    def test_single_dot_normalized(self):
        # os.path.normpath("./foo.py") → "foo.py"
        result = validate_file_path("./foo.py")
        assert result == "foo.py"


# ---------------------------------------------------------------------------
# get_file_content
# ---------------------------------------------------------------------------

class TestGetFileContent:
    @pytest.mark.asyncio
    async def test_calls_git_show_with_branch_path(self):
        with patch("src.git.operations.run_git", return_value="file content") as mock_rg:
            result = await get_file_content(REPO, "main", "src/app.py")
        assert result == "file content"
        mock_rg.assert_called_once_with(REPO, "show", "main:src/app.py")

    @pytest.mark.asyncio
    async def test_invalid_path_raises_value_error(self):
        with pytest.raises(ValueError):
            await get_file_content(REPO, "main", "../secret.txt")

    @pytest.mark.asyncio
    async def test_absolute_path_raises_value_error(self):
        with pytest.raises(ValueError):
            await get_file_content(REPO, "main", "/etc/passwd")

    @pytest.mark.asyncio
    async def test_git_error_propagates(self):
        with patch("src.git.operations.run_git", side_effect=subprocess.CalledProcessError(128, "git")):
            with pytest.raises(subprocess.CalledProcessError):
                await get_file_content(REPO, "main", "src/app.py")


# ---------------------------------------------------------------------------
# rebase_branch
# ---------------------------------------------------------------------------

class TestRebaseBranch:
    @pytest.mark.asyncio
    async def test_success_returns_true(self):
        with patch("src.git.operations.run_git", return_value=""):
            success, msg = await rebase_branch(REPO, "main")
        assert success is True
        assert "succeeded" in msg.lower()

    @pytest.mark.asyncio
    async def test_conflict_returns_false_and_aborts(self):
        err = subprocess.CalledProcessError(1, "git", stderr=b"CONFLICT in file.py")

        async def _side_effect(cwd, *args, **kwargs):
            if args[0] == "rebase" and args[1] == "main":
                raise err
            return ""  # abort call succeeds

        with patch("src.git.operations.run_git", side_effect=_side_effect) as mock_rg:
            success, msg = await rebase_branch(REPO, "main")

        assert success is False
        assert "conflict" in msg.lower()
        abort_calls = [c for c in mock_rg.call_args_list if "--abort" in c[0]]
        assert len(abort_calls) == 1

    @pytest.mark.asyncio
    async def test_timeout_returns_false_and_aborts(self):
        async def _side_effect(cwd, *args, **kwargs):
            if args[0] == "rebase" and "--abort" not in args:
                raise asyncio.TimeoutError()
            return ""

        with patch("src.git.operations.run_git", side_effect=_side_effect) as mock_rg:
            success, msg = await rebase_branch(REPO, "main")

        assert success is False
        assert "timed out" in msg.lower()
        abort_calls = [c for c in mock_rg.call_args_list if "--abort" in c[0]]
        assert len(abort_calls) == 1

    @pytest.mark.asyncio
    async def test_abort_failure_during_conflict_is_swallowed(self):
        async def _side_effect(cwd, *args, **kwargs):
            raise subprocess.CalledProcessError(1, "git", stderr=b"conflict")

        with patch("src.git.operations.run_git", side_effect=_side_effect):
            success, msg = await rebase_branch(REPO, "main")

        assert success is False  # Should not raise even if abort also fails

    @pytest.mark.asyncio
    async def test_stderr_included_in_message(self):
        err = subprocess.CalledProcessError(1, "git", stderr=b"CONFLICT in main.py: Merge conflict")
        async def _side_effect(cwd, *args, **kwargs):
            if "--abort" not in args:
                raise err
            return ""

        with patch("src.git.operations.run_git", side_effect=_side_effect):
            success, msg = await rebase_branch(REPO, "main")

        assert "CONFLICT" in msg


# ---------------------------------------------------------------------------
# commit_worktree_changes
# ---------------------------------------------------------------------------

class TestCommitWorktreeChanges:
    @pytest.mark.asyncio
    async def test_returns_true_when_changes_committed(self):
        """add succeeds, diff --cached raises (has staged changes), commit succeeds."""
        async def _side_effect(cwd, *args, **kwargs):
            if args == ("add", "-A"):
                return ""
            if args == ("diff", "--cached", "--quiet"):
                raise subprocess.CalledProcessError(1, "git")  # has changes
            if args[0] == "commit":
                return ""
            return ""

        with patch("src.git.operations.run_git", side_effect=_side_effect):
            result = await commit_worktree_changes(REPO, "my message")

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_nothing_staged(self):
        """diff --cached --quiet returns 0 → nothing to commit."""
        async def _side_effect(cwd, *args, **kwargs):
            return ""  # all commands succeed (including diff --cached --quiet)

        with patch("src.git.operations.run_git", side_effect=_side_effect):
            result = await commit_worktree_changes(REPO, "msg")

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_add_fails(self):
        async def _side_effect(cwd, *args, **kwargs):
            if args == ("add", "-A"):
                raise subprocess.CalledProcessError(1, "git")
            return ""

        with patch("src.git.operations.run_git", side_effect=_side_effect):
            result = await commit_worktree_changes(REPO, "msg")

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_commit_fails(self):
        async def _side_effect(cwd, *args, **kwargs):
            if args == ("add", "-A"):
                return ""
            if args == ("diff", "--cached", "--quiet"):
                raise subprocess.CalledProcessError(1, "git")
            if args[0] == "commit":
                raise subprocess.CalledProcessError(1, "git")
            return ""

        with patch("src.git.operations.run_git", side_effect=_side_effect):
            result = await commit_worktree_changes(REPO, "msg")

        assert result is False

    @pytest.mark.asyncio
    async def test_commit_message_passed(self):
        async def _side_effect(cwd, *args, **kwargs):
            if args == ("add", "-A"):
                return ""
            if args == ("diff", "--cached", "--quiet"):
                raise subprocess.CalledProcessError(1, "git")
            return ""

        with patch("src.git.operations.run_git", side_effect=_side_effect) as mock_rg:
            await commit_worktree_changes(REPO, "custom commit message")

        commit_calls = [c for c in mock_rg.call_args_list if c[0][1] == "commit"]
        assert any("custom commit message" in str(c) for c in commit_calls)


# ---------------------------------------------------------------------------
# merge_branch
# ---------------------------------------------------------------------------

class TestMergeBranch:
    @pytest.mark.asyncio
    async def test_success_returns_true_and_sha(self):
        async def _run_git_side(cwd, *args, **kwargs):
            if args[0] == "checkout":
                return ""
            if args[0] == "merge":
                return ""
            if args == ("rev-parse", "HEAD"):
                return "abc123sha"
            return ""

        with patch("src.git.operations.run_git", side_effect=_run_git_side):
            success, msg = await merge_branch(REPO, "feature", base="main")

        assert success is True
        assert msg == "abc123sha"

    @pytest.mark.asyncio
    async def test_no_base_uses_current_branch(self):
        with patch("src.git.operations.get_current_branch", return_value="develop") as mock_gcb:
            async def _run_git_side(cwd, *args, **kwargs):
                if args[0] == "checkout":
                    assert args[1] == "develop"
                    return ""
                if args[0] == "merge":
                    return ""
                if args == ("rev-parse", "HEAD"):
                    return "sha"
                return ""

            with patch("src.git.operations.run_git", side_effect=_run_git_side):
                success, _ = await merge_branch(REPO, "feature")

        mock_gcb.assert_called_once_with(REPO)
        assert success is True

    @pytest.mark.asyncio
    async def test_conflict_returns_false_and_aborts(self):
        err = subprocess.CalledProcessError(1, "git", stderr=b"merge conflict")

        async def _run_git_side(cwd, *args, **kwargs):
            if args[0] == "checkout":
                return ""
            if args[0] == "merge" and "--abort" not in args:
                raise err
            return ""  # abort

        with patch("src.git.operations.run_git", side_effect=_run_git_side) as mock_rg:
            success, msg = await merge_branch(REPO, "feature", base="main")

        assert success is False
        assert "merge conflict" in msg
        abort_calls = [c for c in mock_rg.call_args_list if "--abort" in c[0]]
        assert len(abort_calls) == 1

    @pytest.mark.asyncio
    async def test_custom_commit_message_used(self):
        async def _run_git_side(cwd, *args, **kwargs):
            if args[0] == "checkout":
                return ""
            if args[0] == "merge":
                assert "Custom message" in args
                return ""
            if args == ("rev-parse", "HEAD"):
                return "sha"
            return ""

        with patch("src.git.operations.run_git", side_effect=_run_git_side):
            success, _ = await merge_branch(REPO, "feature", base="main",
                                            commit_message="Custom message")
        assert success is True

    @pytest.mark.asyncio
    async def test_with_worktree_commits_first(self, tmp_path):
        worktree = tmp_path / "wt"
        worktree.mkdir()

        with patch("src.git.operations.commit_worktree_changes", return_value=True) as mock_cwc:
            async def _run_git_side(cwd, *args, **kwargs):
                if args[0] in ("checkout", "merge"):
                    return ""
                if args == ("rev-parse", "HEAD"):
                    return "sha"
                return ""

            with patch("src.git.operations.run_git", side_effect=_run_git_side):
                success, _ = await merge_branch(REPO, "feature", base="main",
                                                worktree_path=worktree)

        mock_cwc.assert_called_once()
        assert success is True

    @pytest.mark.asyncio
    async def test_worktree_not_exists_skips_commit(self, tmp_path):
        nonexistent = tmp_path / "no_wt"

        with patch("src.git.operations.commit_worktree_changes") as mock_cwc:
            async def _run_git_side(cwd, *args, **kwargs):
                if args[0] in ("checkout", "merge"):
                    return ""
                if args == ("rev-parse", "HEAD"):
                    return "sha"
                return ""

            with patch("src.git.operations.run_git", side_effect=_run_git_side):
                await merge_branch(REPO, "feature", base="main", worktree_path=nonexistent)

        mock_cwc.assert_not_called()

    @pytest.mark.asyncio
    async def test_abort_failure_during_conflict_is_swallowed(self):
        async def _run_git_side(cwd, *args, **kwargs):
            if args[0] == "checkout":
                return ""
            raise subprocess.CalledProcessError(1, "git", stderr=b"err")

        with patch("src.git.operations.run_git", side_effect=_run_git_side):
            success, msg = await merge_branch(REPO, "feature", base="main")

        assert success is False  # Should not raise
