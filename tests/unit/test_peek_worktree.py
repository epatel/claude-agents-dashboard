"""Unit tests for the peek_worktree tool.

Three layers: the MCP tool server (src/agent/peek_worktree.py), the git reads
that back it (GitService.worktree_changes / worktree_path_diff), and the text
WorkflowService.peek_worktree renders for the agent.
"""

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from src.database import Database
from src.services.database_service import DatabaseService
from src.services.git_service import GitService
from src.services.notification_service import NotificationService
from src.services.session_service import SessionService
from src.services.workflow_service import WorkflowService


# ── MCP tool server ────────────────────────────────────────────────────

def _capture_tools(callback):
    captured = {}

    def fake_server(name, tools):
        captured["name"] = name
        captured["tools"] = tools
        return {}

    from src.agent.peek_worktree import create_peek_worktree_server
    with patch("src.agent.peek_worktree.create_sdk_mcp_server", fake_server):
        create_peek_worktree_server(callback)
    return captured


class TestPeekWorktreeServer:
    def test_server_and_tool_names(self):
        cap = _capture_tools(AsyncMock(return_value=""))
        assert cap["name"] == "peek_worktree"
        assert [t.name for t in cap["tools"]] == ["peek_worktree"]

    def test_both_arguments_are_optional(self):
        cap = _capture_tools(AsyncMock(return_value=""))
        schema = cap["tools"][0].input_schema
        assert set(schema["properties"]) == {"item_id", "path"}
        assert not schema.get("required")

    async def test_no_args_passes_none_through(self):
        cb = AsyncMock(return_value="summary")
        cap = _capture_tools(cb)
        result = await cap["tools"][0].handler({})
        cb.assert_awaited_once_with(None, None)
        assert result["content"][0]["text"] == "summary"

    async def test_item_id_and_path_are_forwarded(self):
        cb = AsyncMock(return_value="diff")
        cap = _capture_tools(cb)
        await cap["tools"][0].handler({"item_id": "abc", "path": "src/foo.py"})
        cb.assert_awaited_once_with("abc", "src/foo.py")

    async def test_blank_strings_are_normalized_to_none(self):
        cb = AsyncMock(return_value="")
        cap = _capture_tools(cb)
        await cap["tools"][0].handler({"item_id": "", "path": ""})
        cb.assert_awaited_once_with(None, None)


# ── GitService reads ───────────────────────────────────────────────────

class TestGitServiceWorktreeReads:
    @pytest.fixture
    def git(self, tmp_path):
        return GitService(tmp_path / "repo", tmp_path / "worktrees")

    async def test_worktree_changes_diffs_against_base_commit(self, git, tmp_path):
        wt = tmp_path / "wt"
        with patch("src.services.git_service.get_changed_files",
                   new_callable=AsyncMock) as mock_changed:
            mock_changed.return_value = [{"status": "M", "status_label": "Modified",
                                          "path": "src/a.py"}]
            files = await git.worktree_changes(wt, "agent/1", base_branch="main",
                                               base_commit="abc123")
        assert files == [{"status": "M", "status_label": "Modified", "path": "src/a.py"}]
        mock_changed.assert_awaited_once_with(
            wt, "agent/1", base="main", worktree_path=wt, base_commit="abc123"
        )

    async def test_path_diff_prefers_base_commit_over_branch(self, git, tmp_path):
        wt = tmp_path / "wt"
        wt.mkdir()
        with patch("src.services.git_service.run_git", new_callable=AsyncMock) as mock_git:
            mock_git.return_value = "diff --git a/src/a.py b/src/a.py\n+x"
            out = await git.worktree_path_diff(wt, "src/a.py", base_branch="main",
                                               base_commit="abc123")
        mock_git.assert_awaited_once_with(wt, "diff", "abc123", "--", "src/a.py")
        assert "+x" in out

    async def test_path_diff_rejects_traversal(self, git, tmp_path):
        with pytest.raises(ValueError):
            await git.worktree_path_diff(tmp_path / "wt", "../../etc/passwd")

    async def test_path_diff_synthesizes_add_for_untracked_file(self, git, tmp_path):
        wt = tmp_path / "wt"
        wt.mkdir()
        (wt / "new.py").write_text("print(1)\n")
        with patch("src.services.git_service.run_git", new_callable=AsyncMock) as mock_git:
            mock_git.return_value = ""  # git diff knows nothing about untracked files
            out = await git.worktree_path_diff(wt, "new.py", base_commit="abc123")
        assert "new file mode" in out
        assert "+print(1)" in out

    async def test_path_diff_survives_git_failure(self, git, tmp_path):
        wt = tmp_path / "wt"
        wt.mkdir()
        with patch("src.services.git_service.run_git", new_callable=AsyncMock) as mock_git:
            mock_git.side_effect = subprocess.CalledProcessError(1, ["git", "diff"])
            out = await git.worktree_path_diff(wt, "missing.py", base_commit="abc123")
        assert out == ""


# ── WorkflowService rendering ──────────────────────────────────────────

@pytest_asyncio.fixture
async def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest_asyncio.fixture
async def db_service(tmp_dir):
    database = Database(tmp_dir / "test.db")
    await database.initialize()
    return DatabaseService(database)


@pytest_asyncio.fixture
async def workflow(db_service, tmp_dir):
    git_service = MagicMock(spec=GitService)
    git_service.target_project = tmp_dir
    git_service.worktree_dir = tmp_dir / "worktrees"
    git_service.worktree_dir.mkdir(exist_ok=True)

    ws_manager = MagicMock()
    ws_manager.broadcast = AsyncMock()
    notif = NotificationService(ws_manager)

    sessions = MagicMock(spec=SessionService)
    sessions.sessions = {}

    return WorkflowService(db_service, git_service, notif, sessions, tmp_dir)


async def _agent_item(workflow, db_service, title, files):
    """Create an item with a real worktree dir and stub its changed files."""
    item = await db_service.create_todo_item(title, "")
    wt = workflow.git.worktree_dir / f"agent-{item['id']}"
    wt.mkdir(parents=True, exist_ok=True)
    await db_service.update_item(
        item["id"], column_name="doing", status="running",
        worktree_path=str(wt), branch_name=f"agent/{item['id']}",
        base_branch="main", base_commit="abc123",
    )
    workflow._peek_files = getattr(workflow, "_peek_files", {})
    workflow._peek_files[item["id"]] = [
        {"status": "M", "status_label": "Modified", "path": p} for p in files
    ]

    async def worktree_changes(path, branch, base_branch=None, base_commit=None):
        for iid, entries in workflow._peek_files.items():
            if str(path).endswith(iid):
                return entries
        return []

    workflow.git.worktree_changes = AsyncMock(side_effect=worktree_changes)
    return item["id"]


class TestPeekWorktreeRendering:
    async def test_reports_when_nothing_else_is_in_flight(self, workflow, db_service):
        me = await _agent_item(workflow, db_service, "Mine", ["src/a.py"])
        text = await workflow.peek_worktree(me)
        assert "No other agent has a worktree" in text

    async def test_summary_lists_other_agents_files_and_skips_own(self, workflow, db_service):
        me = await _agent_item(workflow, db_service, "Mine", ["src/a.py"])
        other = await _agent_item(workflow, db_service, "Theirs", ["src/b.py"])
        text = await workflow.peek_worktree(me)
        assert other in text
        assert "src/b.py" in text
        assert "Mine" not in text

    async def test_summary_flags_overlapping_files(self, workflow, db_service):
        me = await _agent_item(workflow, db_service, "Mine", ["src/shared.py"])
        other = await _agent_item(workflow, db_service, "Theirs",
                                  ["src/shared.py", "src/other.py"])
        text = await workflow.peek_worktree(me)
        assert "CONFLICT RISK" in text
        assert f"[{other}] src/shared.py" in text
        assert text.count("YOU ARE ALSO CHANGING THIS") == 1

    async def test_no_conflict_section_when_files_are_disjoint(self, workflow, db_service):
        me = await _agent_item(workflow, db_service, "Mine", ["src/a.py"])
        await _agent_item(workflow, db_service, "Theirs", ["src/b.py"])
        text = await workflow.peek_worktree(me)
        assert "CONFLICT RISK" not in text

    async def test_targeted_peek_returns_full_file_list(self, workflow, db_service):
        me = await _agent_item(workflow, db_service, "Mine", ["src/a.py"])
        other = await _agent_item(workflow, db_service, "Theirs", ["src/b.py", "src/c.py"])
        text = await workflow.peek_worktree(me, other)
        assert "2 changed file(s)" in text
        assert "src/b.py" in text and "src/c.py" in text

    async def test_unknown_target_lists_available_worktrees(self, workflow, db_service):
        me = await _agent_item(workflow, db_service, "Mine", ["src/a.py"])
        other = await _agent_item(workflow, db_service, "Theirs", ["src/b.py"])
        text = await workflow.peek_worktree(me, "does-not-exist")
        assert "No active worktree for item does-not-exist" in text
        assert other in text

    async def test_item_without_worktree_on_disk_is_ignored(self, workflow, db_service):
        me = await _agent_item(workflow, db_service, "Mine", ["src/a.py"])
        gone = await db_service.create_todo_item("Gone", "")
        await db_service.update_item(gone["id"], worktree_path="/nope/missing")
        text = await workflow.peek_worktree(me)
        assert gone["id"] not in text

    async def test_path_peek_returns_the_diff(self, workflow, db_service):
        me = await _agent_item(workflow, db_service, "Mine", ["src/a.py"])
        other = await _agent_item(workflow, db_service, "Theirs", ["src/b.py"])
        workflow.git.worktree_path_diff = AsyncMock(return_value="@@\n+added line")
        text = await workflow.peek_worktree(me, other, "src/b.py")
        assert "File: src/b.py" in text
        assert "+added line" in text

    async def test_path_peek_truncates_long_diffs(self, workflow, db_service):
        from src.services.workflow_service import _PEEK_MAX_DIFF_LINES
        me = await _agent_item(workflow, db_service, "Mine", ["src/a.py"])
        other = await _agent_item(workflow, db_service, "Theirs", ["src/b.py"])
        workflow.git.worktree_path_diff = AsyncMock(
            return_value="\n".join(f"+line {i}" for i in range(_PEEK_MAX_DIFF_LINES + 50))
        )
        text = await workflow.peek_worktree(me, other, "src/b.py")
        assert "diff truncated (50 more lines)" in text

    async def test_invalid_path_is_reported_not_raised(self, workflow, db_service):
        me = await _agent_item(workflow, db_service, "Mine", ["src/a.py"])
        other = await _agent_item(workflow, db_service, "Theirs", ["src/b.py"])
        workflow.git.worktree_path_diff = AsyncMock(side_effect=ValueError("nope"))
        text = await workflow.peek_worktree(me, other, "../secrets")
        assert "Invalid path" in text

    async def test_git_failure_degrades_to_empty_file_list(self, workflow, db_service):
        me = await _agent_item(workflow, db_service, "Mine", ["src/a.py"])
        await _agent_item(workflow, db_service, "Theirs", ["src/b.py"])
        workflow.git.worktree_changes = AsyncMock(side_effect=RuntimeError("git exploded"))
        text = await workflow.peek_worktree(me)
        assert "(no changes yet)" in text


class TestPeekCallbackWiring:
    async def test_callback_closes_over_caller_item_id(self, workflow, db_service):
        me = await _agent_item(workflow, db_service, "Mine", ["src/a.py"])
        other = await _agent_item(workflow, db_service, "Theirs", ["src/b.py"])
        cb = workflow._create_on_peek_worktree_callback(me)
        text = await cb()
        assert other in text

    async def test_session_kwargs_carry_the_callback(self, workflow, db_service):
        item = await db_service.create_todo_item("Mine", "")
        kwargs = await workflow._item_session_kwargs(item)
        assert callable(kwargs["on_peek_worktree"])
