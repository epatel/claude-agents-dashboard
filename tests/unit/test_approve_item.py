"""approve_item merge pipeline: one test per exit path.

Blocked (no base branch / dirty-file overlap), clean merge, rebase-then-merge,
restart with the previous diff, retry cap, and conflict with no diff captured.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# Reuse the WorkflowService fixtures (real DB, mocked git/sessions).
from tests.unit.test_workflow_service import (  # noqa: F401
    db, db_service, item, tmp_dir, workflow,
)


@pytest_asyncio.fixture
async def review_item(db_service, item, tmp_dir):
    wt = tmp_dir / "worktrees" / "merge"
    wt.mkdir(parents=True, exist_ok=True)
    await db_service.update_item(
        item["id"], column_name="review", status=None,
        worktree_path=str(wt), branch_name="agent/merge", base_branch="main",
    )
    return await db_service.get_item(item["id"])


@pytest.fixture(autouse=True)
def git(workflow):
    workflow.git.base_repo_path = MagicMock(return_value=Path("/tmp"))
    workflow.git.merge_agent_work = AsyncMock(return_value=(True, "deadbeefcafe"))
    workflow.git.rebase_onto_base = AsyncMock(return_value=(False, "rebase conflict"))
    return workflow.git


async def approve(workflow, item_id, *, status="", agent_files="", diff="+agent change"):
    """Run approve_item against a fake git; return (item, run_git calls)."""
    calls = []

    async def run_git(cwd, *args, **kwargs):
        calls.append(args)
        if args[0] == "status":
            return status
        if args[:2] == ("diff", "--name-only"):
            return agent_files
        return diff if args[0] == "diff" else ""

    with patch("src.git.operations.run_git", new=run_git), \
         patch("src.git.operations.get_changed_files", new=AsyncMock(return_value=["foo.py"])), \
         patch("src.git.operations.commit_worktree_changes", new=AsyncMock()):
        result = await workflow.approve_item(item_id)
    return result, calls


def ws_events(workflow, name):
    return [c.args[1] for c in workflow.notifications.ws_manager.broadcast.await_args_list
            if c.args[0] == name]


def logged(workflow):
    return [c.args[2] for c in workflow.notifications.broadcast_agent_log.await_args_list]


async def test_missing_base_branch_blocks_merge(workflow, db_service, review_item):
    await db_service.update_item(review_item["id"], base_branch=None)
    result = await workflow.approve_item(review_item["id"])
    assert result["status"] == "merge_blocked"
    assert "no recorded base branch" in ws_events(workflow, "merge_blocked")[0]["message"]
    workflow.git.merge_agent_work.assert_not_called()


@pytest.mark.parametrize("dirty, blocked", [(" M foo.py\n?? new.txt\n", True), (" M other.py\n", False)])
async def test_dirty_base_repo_blocks_only_on_overlap(workflow, review_item, dirty, blocked):
    result, _ = await approve(workflow, review_item["id"], status=dirty, agent_files="foo.py\n")
    if blocked:
        assert result["status"] == "merge_blocked"
        assert "foo.py" in ws_events(workflow, "merge_blocked")[0]["message"]
        workflow.git.merge_agent_work.assert_not_called()
    else:
        assert result["column_name"] == "done"
        assert result["merge_commit"] == "deadbeefcafe"
        workflow.git.cleanup_worktree_and_branch.assert_awaited_once()


async def test_rebase_then_merge_succeeds(workflow, review_item):
    workflow.git.merge_agent_work = AsyncMock(side_effect=[(False, "conflict"), (True, "feedface0000")])
    workflow.git.rebase_onto_base = AsyncMock(return_value=(True, "ok"))
    result, _ = await approve(workflow, review_item["id"])
    assert result["column_name"] == "done"
    assert result["merge_commit"] == "feedface0000"
    assert any("after rebase" in msg for msg in logged(workflow))
    workflow.sessions.create_session.assert_not_called()


async def test_failed_rebase_restarts_agent_with_diff(workflow, review_item):
    workflow.git.merge_agent_work = AsyncMock(return_value=(False, "conflict"))
    result, calls = await approve(workflow, review_item["id"], diff="+my previous work")
    assert result["status"] == "resolving_conflicts"
    assert ("reset", "--hard", "main") in calls
    assert workflow._merge_retries[review_item["id"]] == 1
    prompt = workflow.sessions.start_session_task.await_args.args[2]
    assert "+my previous work" in prompt and "merge conflict" in prompt


@pytest.mark.parametrize("retries, diff", [(2, "+agent change"), (0, "")])
async def test_retry_cap_or_missing_diff_marks_conflict(workflow, review_item, retries, diff):
    workflow.git.merge_agent_work = AsyncMock(return_value=(False, "conflict"))
    workflow._merge_retries[review_item["id"]] = retries
    result, _ = await approve(workflow, review_item["id"], diff=diff)
    assert result["status"] == "conflict"
    workflow.sessions.create_session.assert_not_called()
