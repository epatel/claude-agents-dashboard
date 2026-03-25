"""
P0 Priority Integration Tests: Orchestrator Lifecycle (Start → Complete → Merge)

Tests the complete agent workflow through the refactored service architecture.
"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from src.agent.orchestrator import AgentOrchestrator
from src.agent.session import AgentResult


async def _start_and_get_session(orchestrator, item_id, mock_git_operations):
    """Helper: start agent with mocked git/session start, return the created session."""
    with patch.object(orchestrator.session_service, 'start_session_task', new_callable=AsyncMock):
        item = await orchestrator.start_agent(item_id)
    session = orchestrator.session_service.sessions.get(item_id)
    return item, session


async def _simulate_completion(session, result):
    """Helper: trigger the on_complete callback stored on the session."""
    if session and session.on_complete:
        await session.on_complete(result)


@pytest.mark.integration
class TestOrchestratorLifecycle:
    """Integration tests for the complete orchestrator lifecycle."""

    async def test_complete_agent_lifecycle_success(
        self, test_orchestrator, test_item, mock_git_operations
    ):
        """Test successful complete lifecycle: start → complete → merge."""
        item_id = test_item["id"]

        item, session = await _start_and_get_session(test_orchestrator, item_id, mock_git_operations)

        assert item["column_name"] == "doing"
        assert item["status"] == "running"
        assert item["branch_name"] == f"agent/{item_id}"
        assert item_id in test_orchestrator.sessions

        # Simulate agent completion
        result = AgentResult(success=True, session_id="test-session-123",
                             input_tokens=150, output_tokens=300, total_tokens=450, cost_usd=0.0123)
        await _simulate_completion(session, result)

        async with test_orchestrator.db.connect() as conn:
            cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
            item = dict(await cursor.fetchone())

        assert item["column_name"] == "review"
        assert item["session_id"] == "test-session-123"

        # Test approval/merge
        with patch.object(test_orchestrator.git_service, 'merge_agent_work',
                          new_callable=AsyncMock, return_value=(True, "ok")), \
             patch.object(test_orchestrator.git_service, 'cleanup_worktree_and_branch',
                          new_callable=AsyncMock):
            await test_orchestrator.approve_item(item_id)

            async with test_orchestrator.db.connect() as conn:
                cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
                final_item = dict(await cursor.fetchone())

            assert final_item["column_name"] == "done"

    async def test_agent_lifecycle_with_failure(
        self, test_orchestrator, test_item, mock_git_operations
    ):
        """Test lifecycle when agent fails."""
        item_id = test_item["id"]

        item, session = await _start_and_get_session(test_orchestrator, item_id, mock_git_operations)

        result = AgentResult(success=False, session_id="test-session-456", error="Agent execution failed")
        await _simulate_completion(session, result)

        async with test_orchestrator.db.connect() as conn:
            cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
            item = dict(await cursor.fetchone())

        assert item["status"] == "failed"

    async def test_agent_cancellation(
        self, test_orchestrator, test_item, mock_git_operations
    ):
        """Test cancelling a running agent."""
        item_id = test_item["id"]

        item, session = await _start_and_get_session(test_orchestrator, item_id, mock_git_operations)
        assert item_id in test_orchestrator.sessions

        result = await test_orchestrator.cancel_agent(item_id)

        assert result["column_name"] == "todo"
        assert result["status"] == "cancelled"
        assert item_id not in test_orchestrator.sessions

    async def test_review_feedback_loop(
        self, test_orchestrator, test_item, mock_git_operations
    ):
        """Test review feedback and agent restart."""
        item_id = test_item["id"]

        item, session = await _start_and_get_session(test_orchestrator, item_id, mock_git_operations)

        result = AgentResult(success=True, session_id="test-session-123")
        await _simulate_completion(session, result)

        async with test_orchestrator.db.connect() as conn:
            cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
            item = dict(await cursor.fetchone())
        assert item["column_name"] == "review"

        # Request changes
        with patch.object(test_orchestrator.session_service, 'start_session_task', new_callable=AsyncMock):
            comments = ["Fix the formatting", "Add more tests"]
            updated_item = await test_orchestrator.request_changes(item_id, comments)

        assert updated_item["column_name"] == "doing"
        assert updated_item["status"] == "running"

        # Verify comments were stored
        async with test_orchestrator.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT content FROM review_comments WHERE item_id = ? ORDER BY content",
                (item_id,)
            )
            stored_comments = [row[0] for row in await cursor.fetchall()]
        assert stored_comments == ["Add more tests", "Fix the formatting"]

    async def test_review_cancellation_cleanup(
        self, test_orchestrator, test_item, mock_git_operations
    ):
        """Test cancelling review and cleaning up worktree."""
        item_id = test_item["id"]

        await test_orchestrator._update_item(
            item_id,
            column_name="review",
            branch_name=f"agent/{item_id}",
            worktree_path="/mock/worktree"
        )

        with patch.object(test_orchestrator.git_service, 'cleanup_worktree_and_branch',
                          new_callable=AsyncMock) as mock_cleanup:
            result = await test_orchestrator.cancel_review(item_id)

            assert result["column_name"] == "todo"
            assert result["status"] is None
            mock_cleanup.assert_called_once()

    async def test_agent_retry_after_failure(
        self, test_orchestrator, test_item, mock_git_operations
    ):
        """Test retrying a failed agent."""
        item_id = test_item["id"]

        await test_orchestrator._update_item(
            item_id,
            status="failed",
            column_name="doing",
            branch_name=f"agent/{item_id}",
            worktree_path="/mock/worktree"
        )

        with patch.object(test_orchestrator.session_service, 'start_session_task', new_callable=AsyncMock):
            result = await test_orchestrator.retry_agent(item_id)

        assert result["column_name"] == "doing"
        assert result["status"] == "running"

    async def test_merge_conflict_handling(
        self, test_orchestrator, test_item, mock_git_operations
    ):
        """Test handling of merge conflicts during approval."""
        item_id = test_item["id"]

        await test_orchestrator._update_item(
            item_id,
            column_name="review",
            branch_name=f"agent/{item_id}",
            worktree_path="/mock/worktree"
        )

        with patch.object(test_orchestrator.git_service, 'merge_agent_work',
                          new_callable=AsyncMock,
                          return_value=(False, "Merge conflict in file.txt")):
            result = await test_orchestrator.approve_item(item_id)
            assert result["status"] == "resolving_conflicts"

    async def test_clarification_workflow(
        self, test_orchestrator, test_item, mock_git_operations
    ):
        """Test the clarification request and response workflow."""
        item_id = test_item["id"]
        prompt = "What color should the button be?"
        choices = ["red", "blue", "green"]

        await test_orchestrator._update_item(item_id, column_name="doing", status="running")

        callback = test_orchestrator.workflow_service._create_on_clarify_callback(item_id)
        clarification_task = asyncio.create_task(callback(prompt, choices))
        await asyncio.sleep(0.01)

        async with test_orchestrator.db.connect() as conn:
            cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
            item = dict(await cursor.fetchone())
        assert item["column_name"] == "clarify"

        await test_orchestrator.submit_clarification(item_id, "blue")
        response = await clarification_task
        assert response == "blue"

    async def test_commit_message_handling(
        self, test_orchestrator, test_item, mock_git_operations
    ):
        """Test commit message setting and usage during merge."""
        item_id = test_item["id"]
        commit_message = "Add new feature: user authentication"

        item, session = await _start_and_get_session(test_orchestrator, item_id, mock_git_operations)

        # Set commit message AFTER session is created (simulates agent calling the tool)
        test_orchestrator.session_service.set_commit_message(item_id, commit_message)

        result = AgentResult(success=True, session_id="test-session")
        await _simulate_completion(session, result)

        async with test_orchestrator.db.connect() as conn:
            cursor = await conn.execute("SELECT commit_message FROM items WHERE id = ?", (item_id,))
            stored_message = (await cursor.fetchone())[0]
        assert stored_message == commit_message

    async def test_token_usage_tracking(
        self, test_orchestrator, test_item, mock_git_operations
    ):
        """Test that token usage is properly tracked and stored."""
        item_id = test_item["id"]

        item, session = await _start_and_get_session(test_orchestrator, item_id, mock_git_operations)

        result = AgentResult(success=True, session_id="test-session-789",
                             input_tokens=250, output_tokens=150, total_tokens=400, cost_usd=0.0456)
        await _simulate_completion(session, result)

        async with test_orchestrator.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT * FROM token_usage WHERE item_id = ?", (item_id,)
            )
            usage = dict(await cursor.fetchone())

        assert usage["input_tokens"] == 250
        assert usage["output_tokens"] == 150
        assert usage["total_tokens"] == 400
        assert abs(usage["cost_usd"] - 0.0456) < 0.0001

    async def test_concurrent_agent_operations(
        self, test_orchestrator, test_db, mock_git_operations
    ):
        """Test running multiple agents concurrently."""
        items = []
        for i in range(3):
            item_id = f"concurrent-item-{i}"
            async with test_db.connect() as conn:
                await conn.execute(
                    """INSERT INTO items (id, title, description, column_name, position)
                       VALUES (?, ?, ?, 'todo', ?)""",
                    (item_id, f"Task {i}", f"Description {i}", i)
                )
                await conn.commit()
            items.append(item_id)

        with patch.object(test_orchestrator.session_service, 'start_session_task', new_callable=AsyncMock):
            tasks = [test_orchestrator.start_agent(item_id) for item_id in items]
            results = await asyncio.gather(*tasks)

            for i, result in enumerate(results):
                assert result["column_name"] == "doing"
                assert result["status"] == "running"

            # Simulate concurrent completions
            for item_id in items:
                session = test_orchestrator.session_service.sessions.get(item_id)
                r = AgentResult(success=True, session_id=f"session-{item_id}")
                await _simulate_completion(session, r)

            # Verify all items moved to review
            async with test_db.connect() as conn:
                for item_id in items:
                    cursor = await conn.execute("SELECT column_name FROM items WHERE id = ?", (item_id,))
                    row = await cursor.fetchone()
                    assert row[0] == "review"

    async def test_error_during_worktree_creation(
        self, test_orchestrator, test_item
    ):
        """Test error handling when worktree creation fails."""
        item_id = test_item["id"]

        with patch.object(test_orchestrator.git_service, 'create_or_reuse_worktree',
                          new_callable=AsyncMock,
                          side_effect=Exception("Git error: unable to create worktree")):
            with pytest.raises(Exception, match="Git error: unable to create worktree"):
                await test_orchestrator.start_agent(item_id)


@pytest.mark.integration
class TestOrchestratorConcurrency:
    """Tests for concurrent orchestrator operations and edge cases."""

    async def test_rapid_cancel_and_restart(
        self, test_orchestrator, test_item, mock_git_operations
    ):
        """Test rapidly cancelling and restarting an agent."""
        item_id = test_item["id"]

        with patch.object(test_orchestrator.session_service, 'start_session_task', new_callable=AsyncMock):
            await test_orchestrator.start_agent(item_id)
            await test_orchestrator.cancel_agent(item_id)
            await test_orchestrator.start_agent(item_id)

        async with test_orchestrator.db.connect() as conn:
            cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
            item = dict(await cursor.fetchone())

        assert item["column_name"] == "doing"
        assert item["status"] == "running"
        assert item_id in test_orchestrator.sessions

    async def test_shutdown_with_active_agents(
        self, test_orchestrator, test_item, mock_git_operations
    ):
        """Test orchestrator shutdown with active agents."""
        item_id = test_item["id"]

        with patch.object(test_orchestrator.session_service, 'start_session_task', new_callable=AsyncMock):
            await test_orchestrator.start_agent(item_id)

        assert item_id in test_orchestrator.sessions

        await test_orchestrator.shutdown()

        assert len(test_orchestrator.sessions) == 0
