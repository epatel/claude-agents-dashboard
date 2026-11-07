"""WorkflowService auto-approve paths: no-changes, DIRECT mode, review badge."""

import asyncio
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from src.agent.session import AgentResult
from tests.unit.workflow_fixtures import (  # noqa: F401
    db, db_service, fake_repo, item, stage_item, tmp_dir, workflow,
)

APPROVED = {"approved": True, "comments": [], "summary": "ok", "raw": ""}


REVIEW = {"column_name": "review", "status": None}
RUNNING = {"column_name": "doing", "status": "running"}


async def stage(workflow, item, worktree, **fields):
    """Point the item at ``worktrees/<worktree>`` on ``agent/<worktree>`` off main."""
    await stage_item(
        workflow, item["id"], worktree,
        branch_name=f"agent/{worktree}", base_branch="main", **fields,
    )
    return item


def assert_done_broadcast(workflow, item_id):
    """The broadcast must include the post-transition item (column=done)."""
    workflow.notifications.broadcast_item_updated.assert_awaited()
    broadcast_args = [
        call.args[0]
        for call in workflow.notifications.broadcast_item_updated.await_args_list
    ]
    assert any(
        arg.get("id") == item_id and arg.get("column_name") == "done"
        for arg in broadcast_args
    ), f"expected a done-column broadcast for {item_id}, got {broadcast_args}"


# ---------------------------------------------------------------------------
# Auto-approve: items without file changes
# ---------------------------------------------------------------------------

class TestAutoApproveNoChanges:
    """Auto-approve must also handle items where the agent finished without
    producing any file changes — i.e. the review card shows a "Done" button
    instead of "Approve & Merge". Without this path the card just sits in
    review forever."""

    @pytest_asyncio.fixture
    async def review_item(self, workflow, item):
        # Item that's landed in review with auto_approve set and a worktree
        # path. No diff (no commits, no modified files) — this is what
        # has_file_changes=0 looks like in practice.
        return await stage(workflow, item, "no-changes", **REVIEW, auto_approve=1,
                           has_file_changes=0)

    async def no_changes_column(self, workflow, item_id):
        # approve_item internally calls run_git("status") and get_changed_files;
        # patch both to simulate a clean repo with zero agent-touched files.
        with fake_repo():
            await workflow._auto_approve_no_changes(item_id)
        return (await workflow.db.get_item(item_id))["column_name"]

    async def test_no_changes_path_moves_item_to_done(self, workflow, review_item):
        assert await self.no_changes_column(workflow, review_item["id"]) == "done"

    async def test_no_changes_path_skips_merge_call(self, workflow, review_item):
        workflow.git.merge_agent_work = AsyncMock(return_value=(True, "ok"))
        await self.no_changes_column(workflow, review_item["id"])
        # No diff → no merge.
        workflow.git.merge_agent_work.assert_not_called()

    async def test_no_changes_path_broadcasts_item_updated(self, workflow, review_item):
        # Regression: the no-changes branch in approve_item used to skip
        # broadcast_item_updated, so the frontend never saw the column change
        # and the card stayed in Review until a reload.
        await self.no_changes_column(workflow, review_item["id"])
        assert_done_broadcast(workflow, review_item["id"])

    async def test_clean_merge_path_broadcasts_item_updated(self, workflow, review_item):
        # Regression: the clean merge-success branch in approve_item also used
        # to skip broadcast_item_updated, leaving the card stuck in Review on
        # auto-approve when the agent did produce file changes.
        # Force the file-changes branch and a successful merge.
        await workflow.db.update_item(review_item["id"], has_file_changes=1)
        workflow.git.merge_agent_work = AsyncMock(return_value=(True, "deadbeefdeadbeef"))
        workflow.git.base_repo_path = MagicMock(return_value=Path("/tmp"))
        with fake_repo(["foo.py"]):
            await workflow.approve_item(review_item["id"])
        assert_done_broadcast(workflow, review_item["id"])

    async def test_no_op_when_item_left_review(self, workflow, review_item):
        # User cancelled review before the auto-approve task ran.
        await workflow.db.update_item(review_item["id"], column_name="todo")
        # Should not have moved out of todo.
        assert await self.no_changes_column(workflow, review_item["id"]) == "todo"

    async def test_no_op_when_auto_approve_unset(self, workflow, review_item):
        await workflow.db.update_item(review_item["id"], auto_approve=0)
        # Stays in review for human action.
        assert await self.no_changes_column(workflow, review_item["id"]) == "review"


# ---------------------------------------------------------------------------
# Auto-approve: DIRECT mode (skip review entirely)
# ---------------------------------------------------------------------------

class TestAutoApproveDirect:
    """auto_approve=2 (DIRECT) means: merge as soon as the agent finishes — no
    review-agent pass. The on_complete callback should dispatch
    _auto_approve_direct, and that helper should call approve_item without
    spawning the reviewer."""

    @pytest_asyncio.fixture
    async def review_item_direct(self, workflow, item):
        return await stage(  # AUTO_APPROVE_DIRECT
            workflow, item, "direct", **REVIEW, auto_approve=2, has_file_changes=1)

    async def test_direct_path_calls_approve_item(self, workflow, review_item_direct):
        # Patch approve_item to confirm it's invoked. We don't care about its
        # internals here — the no-changes/clean-merge tests cover those.
        with patch.object(workflow, "approve_item", new=AsyncMock()) as mock_approve:
            await workflow._auto_approve_direct(review_item_direct["id"])
            mock_approve.assert_awaited_once_with(review_item_direct["id"])

    async def test_direct_path_skips_review_agent(self, workflow, review_item_direct):
        # The reviewer must not be spawned in DIRECT mode — that's the whole
        # point of this mode vs auto_approve=1.
        with patch("src.services.workflow_service.run_auto_review",
                   new=AsyncMock()) as mock_review, \
             patch.object(workflow, "approve_item", new=AsyncMock()):
            await workflow._auto_approve_direct(review_item_direct["id"])
            mock_review.assert_not_called()

    async def direct_no_op(self, workflow, item_id, **fields):
        await workflow.db.update_item(item_id, **fields)
        with patch.object(workflow, "approve_item", new=AsyncMock()) as mock_approve:
            await workflow._auto_approve_direct(item_id)
            mock_approve.assert_not_called()

    async def test_direct_no_op_when_mode_is_review(self, workflow, review_item_direct):
        # Defense in depth: if something dispatched _auto_approve_direct on an
        # item that's actually in REVIEW mode (1), bail out — that path is
        # supposed to go through _run_auto_review, not skip review.
        await self.direct_no_op(workflow, review_item_direct["id"], auto_approve=1)

    async def test_direct_no_op_when_item_left_review(self, workflow, review_item_direct):
        # User cancelled before the background task ran.
        await self.direct_no_op(workflow, review_item_direct["id"], column_name="todo")


# ---------------------------------------------------------------------------
# on_complete: which auto-approve path is dispatched
# ---------------------------------------------------------------------------

async def dispatch_on_complete(workflow, item_id, changed_files, targets):
    """Fire on_complete for a RUNNING item; return which patched path ran.

    ``targets`` maps a WorkflowService method name to the label recorded
    (prefixed to the item id) when on_complete dispatches it.
    """
    called: list[str] = []

    def recorder(label):
        async def fake(iid):
            called.append(f"{label}{iid}")
        return fake

    with ExitStack() as stack:
        stack.enter_context(patch("src.git.operations.get_changed_files",
                                  new=AsyncMock(return_value=changed_files)))
        for name, label in targets.items():
            stack.enter_context(patch.object(workflow, name, side_effect=recorder(label)))
        cb = workflow._create_on_complete_callback(item_id)
        await cb(AgentResult(success=True, session_id="sess-x"))
        # The paths are dispatched as background tasks via
        # asyncio.create_task. Yield once so they get a chance to run.
        await asyncio.sleep(0)
    return called


ON_COMPLETE_CASES = [
    # When auto_approve is set and the agent produced no diff, the
    # on_complete callback must dispatch _auto_approve_no_changes — not just
    # no-op the way it did before. "review:" would indicate the wrong branch.
    pytest.param(dict(
        worktree="no-changes-2", auto_approve=1, changed_files=[],
        targets={"_auto_approve_no_changes": "", "_run_auto_review": "review:"},
        expected="", path="no-changes",
    ), id="schedules_no_changes_auto_approve"),
    # auto_approve=2 must route to _auto_approve_direct, NOT to
    # _run_auto_review or _auto_approve_no_changes. has_file_changes=1 —
    # pretend the agent did produce a diff. Direct mode should bypass review
    # either way.
    pytest.param(dict(
        worktree="direct-2", auto_approve=2, changed_files=["foo.py"],
        targets={
            "_auto_approve_direct": "direct:",
            "_run_auto_review": "review:",
            "_auto_approve_no_changes": "no-changes:",
        },
        expected="direct:", path="direct",
    ), id="dispatches_direct_path"),
]


class TestOnCompleteDispatch:
    @pytest.mark.parametrize("case", ON_COMPLETE_CASES)
    async def test_on_complete_dispatches_auto_approve_path(self, workflow, item, case):
        await stage(workflow, item, case["worktree"], **RUNNING,
                    auto_approve=case["auto_approve"])
        called = await dispatch_on_complete(
            workflow, item["id"], case["changed_files"], case["targets"])
        assert called == [f"{case['expected']}{item['id']}"], (
            f"Expected {case['path']} path to be dispatched, got {called}"
        )


# ---------------------------------------------------------------------------
# Auto-review badge tracking
# ---------------------------------------------------------------------------

@contextmanager
def fake_review(workflow, side_effect, *, approve=True):
    """Patch run_auto_review and run_git (and approve_item when ``approve``)."""
    with ExitStack() as stack:
        stack.enter_context(patch("src.services.workflow_service.run_auto_review",
                                  side_effect=side_effect))
        stack.enter_context(patch("src.git.operations.run_git",
                                  new=AsyncMock(return_value="")))
        if approve:
            stack.enter_context(patch.object(workflow, "approve_item", new=AsyncMock()))
        yield


def review_broadcasts(workflow):
    return [
        call for call in workflow.notifications.ws_manager.broadcast.await_args_list
        if call.args and call.args[0] == "auto_review_changed"
    ]


class TestAutoReviewBadgeTracking:
    """The auto-review agent runs outside the regular session manager, so we
    track in-flight reviews in `_auto_reviewing` and broadcast
    `auto_review_changed` events. The UI uses both to render a "Reviewing"
    badge on review-column cards while the diff is being inspected."""

    @pytest_asyncio.fixture
    async def review_item(self, workflow, item):
        return await stage(  # AUTO_APPROVE_REVIEW
            workflow, item, "review-badge", **REVIEW, auto_approve=1, has_file_changes=1)

    async def test_run_auto_review_marks_and_unmarks_item(self, workflow, review_item):
        # While run_auto_review is awaiting, the item should be in the set;
        # once it resolves, the set should be empty.
        seen_during_review: list[bool] = []

        async def fake_run_review(**kwargs):
            seen_during_review.append(review_item["id"] in workflow._auto_reviewing)
            return APPROVED

        with fake_review(workflow, fake_run_review):
            await workflow._run_auto_review(review_item["id"])

        assert seen_during_review == [True], (
            "item must be marked as auto-reviewing while run_auto_review runs"
        )
        assert review_item["id"] not in workflow._auto_reviewing, (
            "item must be unmarked once review finishes"
        )

    async def test_run_auto_review_broadcasts_events(self, workflow, review_item):
        async def fake_run_review(**kwargs):
            return APPROVED

        with fake_review(workflow, fake_run_review):
            await workflow._run_auto_review(review_item["id"])

        # Two broadcasts: active=True at start, active=False at end.
        review_calls = review_broadcasts(workflow)
        assert len(review_calls) == 2, (
            f"expected 2 auto_review_changed broadcasts, got {len(review_calls)}: "
            f"{review_calls}"
        )
        assert review_calls[0].args[1] == {"item_id": review_item["id"], "active": True}
        assert review_calls[1].args[1] == {"item_id": review_item["id"], "active": False}

    async def test_run_auto_review_unmarks_on_agent_failure(self, workflow, review_item):
        # If the review agent itself raises, we must still clear the badge —
        # otherwise the UI would show "Reviewing" forever.
        async def boom(**kwargs):
            raise RuntimeError("review agent crashed")

        with fake_review(workflow, boom, approve=False):
            # _run_auto_review swallows exceptions internally (logs + bails).
            await workflow._run_auto_review(review_item["id"])

        assert review_item["id"] not in workflow._auto_reviewing, (
            "item must be unmarked even when run_auto_review raises"
        )
        # And the active=False broadcast must still go out.
        assert any(
            call.args[1] == {"item_id": review_item["id"], "active": False}
            for call in review_broadcasts(workflow)
        ), "expected an active=False broadcast on failure"
