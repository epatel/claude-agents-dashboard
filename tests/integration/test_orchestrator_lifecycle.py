"""
P0 Priority Integration Tests: Orchestrator Lifecycle (Start → Complete → Merge)

Tests the complete agent workflow including:
- Agent startup and worktree creation
- Session execution and completion handling
- Merge operations and cleanup
- Error scenarios and cancellation
- Review feedback loop
"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from src.agent.orchestrator import AgentOrchestrator
from src.agent.session import AgentResult


@pytest.mark.integration
class TestOrchestratorLifecycle:
    """Integration tests for the complete orchestrator lifecycle."""

    async def test_complete_agent_lifecycle_success(
        self, test_orchestrator, test_item, mock_git_operations
    ):
        """Test successful complete lifecycle: start → complete → merge."""
        item_id = test_item["id"]

        # Mock AgentSession to simulate successful completion
        mock_session = AsyncMock()
        mock_session.start = AsyncMock()

        # Mock the session result
        result = AgentResult(
            success=True,
            session_id="test-session-123",
            input_tokens=150,
            output_tokens=300,
            total_tokens=450,
            cost_usd=0.0123,
            error=None
        )

        with patch.object(test_orchestrator, '_create_session', return_value=mock_session):
            # Start agent
            updated_item = await test_orchestrator.start_agent(item_id)

            assert updated_item["column_name"] == "doing"
            assert updated_item["status"] == "running"
            assert updated_item["branch_name"] == f"agent/{item_id}"
            assert updated_item["worktree_path"] is not None

            # Verify session was created and started
            assert item_id in test_orchestrator.sessions
            assert item_id in test_orchestrator._agent_tasks
            mock_session.start.assert_called_once()

            # Simulate agent completion
            await test_orchestrator._on_agent_complete(item_id, result)

            # Verify item moved to review column
            async with test_orchestrator.db.connect() as conn:
                cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
                item = dict(await cursor.fetchone())

            assert item["column_name"] == "review"
            assert item["status"] is None
            assert item["session_id"] == "test-session-123"

            # Verify session cleanup
            assert item_id not in test_orchestrator.sessions

            # Test approval/merge
            await test_orchestrator.approve_item(item_id)

            # Verify merge was called
            mock_git_operations['merge_branch'].assert_called_once()
            mock_git_operations['cleanup_worktree'].assert_called_once()

            # Verify item moved to done column
            async with test_orchestrator.db.connect() as conn:
                cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
                final_item = dict(await cursor.fetchone())

            assert final_item["column_name"] == "done"
            assert final_item["status"] is None
            assert final_item["worktree_path"] is None

    async def test_agent_lifecycle_with_failure(
        self, test_orchestrator, test_item, mock_git_operations
    ):
        """Test lifecycle when agent fails."""
        item_id = test_item["id"]

        # Mock AgentSession to simulate failure
        mock_session = AsyncMock()
        mock_session.start = AsyncMock()

        result = AgentResult(
            success=False,
            session_id="test-session-456",
            input_tokens=100,
            output_tokens=0,
            total_tokens=100,
            cost_usd=0.002,
            error="Agent execution failed"
        )

        with patch.object(test_orchestrator, '_create_session', return_value=mock_session):
            # Start agent
            await test_orchestrator.start_agent(item_id)

            # Simulate agent failure
            await test_orchestrator._on_agent_complete(item_id, result)

            # Verify item status shows failure
            async with test_orchestrator.db.connect() as conn:
                cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
                item = dict(await cursor.fetchone())

            assert item["status"] == "failed"
            assert item["column_name"] == "doing"  # Should stay in doing column

            # Verify session cleanup
            assert item_id not in test_orchestrator.sessions

    async def test_agent_cancellation(
        self, test_orchestrator, test_item, mock_git_operations
    ):
        """Test agent cancellation during execution."""
        item_id = test_item["id"]

        # Mock AgentSession
        mock_session = AsyncMock()
        mock_session.start = AsyncMock()
        mock_session.cancel = AsyncMock()

        with patch.object(test_orchestrator, '_create_session', return_value=mock_session):
            # Start agent
            await test_orchestrator.start_agent(item_id)

            # Cancel agent
            result = await test_orchestrator.cancel_agent(item_id)

            assert result["column_name"] == "todo"
            assert result["status"] == "cancelled"

            # Verify session was cancelled
            mock_session.cancel.assert_called_once()

            # Verify cleanup
            assert item_id not in test_orchestrator.sessions
            assert item_id not in test_orchestrator._agent_tasks

    async def test_review_feedback_loop(
        self, test_orchestrator, test_item, mock_git_operations
    ):
        """Test review feedback and agent restart."""
        item_id = test_item["id"]

        # First complete a successful run to get to review state
        mock_session = AsyncMock()
        result = AgentResult(success=True, session_id="test-session-123")

        with patch.object(test_orchestrator, '_create_session', return_value=mock_session):
            await test_orchestrator.start_agent(item_id)
            await test_orchestrator._on_agent_complete(item_id, result)

            # Verify item is in review
            async with test_orchestrator.db.connect() as conn:
                cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
                item = dict(await cursor.fetchone())
            assert item["column_name"] == "review"

            # Request changes
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

            # Verify new session was created
            assert item_id in test_orchestrator.sessions
            mock_session.start.assert_called()

    async def test_review_cancellation_cleanup(
        self, test_orchestrator, test_item, mock_git_operations
    ):
        """Test cancelling review and cleaning up worktree."""
        item_id = test_item["id"]

        # Set up item in review state
        await test_orchestrator._update_item(
            item_id,
            column_name="review",
            branch_name=f"agent/{item_id}",
            worktree_path="/mock/worktree"
        )

        # Cancel review
        result = await test_orchestrator.cancel_review(item_id)

        assert result["column_name"] == "todo"
        assert result["status"] is None
        assert result["worktree_path"] is None

        # Verify cleanup was called
        mock_git_operations['cleanup_worktree'].assert_called_once()

    async def test_agent_retry_after_failure(
        self, test_orchestrator, test_item, mock_git_operations
    ):
        """Test retrying a failed agent."""
        item_id = test_item["id"]

        # Set up item in failed state
        await test_orchestrator._update_item(
            item_id,
            status="failed",
            column_name="doing",
            branch_name=f"agent/{item_id}",
            worktree_path="/mock/worktree"
        )

        mock_session = AsyncMock()
        with patch.object(test_orchestrator, '_create_session', return_value=mock_session):
            # Retry agent
            result = await test_orchestrator.retry_agent(item_id)

            assert result["column_name"] == "doing"
            assert result["status"] == "running"

            # Verify new session was created
            assert item_id in test_orchestrator.sessions
            mock_session.start.assert_called_once()

    async def test_merge_conflict_handling(
        self, test_orchestrator, test_item, mock_git_operations
    ):
        """Test handling of merge conflicts during approval."""
        item_id = test_item["id"]

        # Set up item in review state
        await test_orchestrator._update_item(
            item_id,
            column_name="review",
            branch_name=f"agent/{item_id}",
            worktree_path="/mock/worktree"
        )

        # Mock merge failure
        mock_git_operations['merge_branch'].return_value = (False, "Merge conflict in file.txt")

        result = await test_orchestrator.approve_item(item_id)

        assert result["status"] == "resolving_conflicts"

        # Verify merge was attempted
        mock_git_operations['merge_branch'].assert_called_once()

    async def test_clarification_workflow(
        self, test_orchestrator, test_item, mock_git_operations
    ):
        """Test the clarification request and response workflow."""
        item_id = test_item["id"]
        prompt = "What color should the button be?"
        choices = ["red", "blue", "green"]

        # Start the clarification in background
        async def trigger_clarification():
            return await test_orchestrator._on_clarify(item_id, prompt, choices)

        clarification_task = asyncio.create_task(trigger_clarification())

        # Allow the clarification to set up
        await asyncio.sleep(0.01)

        # Verify item moved to clarify column
        async with test_orchestrator.db.connect() as conn:
            cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
            item = dict(await cursor.fetchone())
        assert item["column_name"] == "clarify"

        # Verify clarification was stored in database
        async with test_orchestrator.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT * FROM clarifications WHERE item_id = ?", (item_id,)
            )
            clarification = dict(await cursor.fetchone())
        assert clarification["prompt"] == prompt

        # Submit response
        await test_orchestrator.submit_clarification(item_id, "blue")

        # Get the result from the clarification
        response = await clarification_task
        assert response == "blue"

        # Verify item moved back to doing
        async with test_orchestrator.db.connect() as conn:
            cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
            item = dict(await cursor.fetchone())
        assert item["column_name"] == "doing"

    async def test_commit_message_handling(
        self, test_orchestrator, test_item, mock_git_operations
    ):
        """Test commit message setting and usage during merge."""
        item_id = test_item["id"]
        commit_message = "Add new feature: user authentication"

        # Set commit message
        result = await test_orchestrator._on_set_commit_message(item_id, commit_message)
        assert "Commit message saved" in result

        # Verify it's stored internally
        assert test_orchestrator._commit_messages[item_id] == commit_message

        # Complete lifecycle to test commit message usage
        mock_session = AsyncMock()
        agent_result = AgentResult(success=True, session_id="test-session")

        with patch.object(test_orchestrator, '_create_session', return_value=mock_session):
            await test_orchestrator.start_agent(item_id)
            await test_orchestrator._on_agent_complete(item_id, agent_result)

            # Verify commit message was saved to item
            async with test_orchestrator.db.connect() as conn:
                cursor = await conn.execute("SELECT commit_message FROM items WHERE id = ?", (item_id,))
                stored_message = (await cursor.fetchone())[0]
            assert stored_message == commit_message

            # Test merge uses the commit message
            await test_orchestrator.approve_item(item_id)
            mock_git_operations['merge_branch'].assert_called_with(
                test_orchestrator.target_project,
                f"agent/{item_id}",
                worktree_path=Path("/mock/worktree"),
                commit_message=commit_message
            )

    async def test_token_usage_tracking(
        self, test_orchestrator, test_item, mock_git_operations
    ):
        """Test that token usage is properly tracked and stored."""
        item_id = test_item["id"]

        result = AgentResult(
            success=True,
            session_id="test-session-789",
            input_tokens=250,
            output_tokens=150,
            total_tokens=400,
            cost_usd=0.0456
        )

        mock_session = AsyncMock()
        with patch.object(test_orchestrator, '_create_session', return_value=mock_session):
            await test_orchestrator.start_agent(item_id)
            await test_orchestrator._on_agent_complete(item_id, result)

            # Verify token usage was saved to database
            async with test_orchestrator.db.connect() as conn:
                cursor = await conn.execute(
                    "SELECT * FROM token_usage WHERE item_id = ?", (item_id,)
                )
                usage = dict(await cursor.fetchone())

            assert usage["input_tokens"] == 250
            assert usage["output_tokens"] == 150
            assert usage["total_tokens"] == 400
            assert usage["cost_usd"] == 0.0456
            assert usage["session_id"] == "test-session-789"

    async def test_concurrent_agent_operations(
        self, test_orchestrator, test_db, mock_git_operations
    ):
        """Test handling multiple concurrent agent operations."""
        # Create multiple test items
        items = []
        for i in range(3):
            item_id = f"test-item-{i}"
            async with test_db.connect() as conn:
                await conn.execute(
                    """INSERT INTO items (id, title, description, column_name, position)
                       VALUES (?, ?, ?, 'todo', ?)""",
                    (item_id, f"Task {i}", f"Description {i}", i)
                )
                await conn.commit()
            items.append(item_id)

        mock_sessions = {item_id: AsyncMock() for item_id in items}

        def create_session_side_effect(item_id, *args, **kwargs):
            return mock_sessions[item_id]

        with patch.object(test_orchestrator, '_create_session', side_effect=create_session_side_effect):
            # Start all agents concurrently
            tasks = [test_orchestrator.start_agent(item_id) for item_id in items]
            results = await asyncio.gather(*tasks)

            # Verify all agents started successfully
            for i, result in enumerate(results):
                assert result["column_name"] == "doing"
                assert result["status"] == "running"
                assert items[i] in test_orchestrator.sessions

            # Simulate concurrent completions
            completion_tasks = []
            for item_id in items:
                result = AgentResult(success=True, session_id=f"session-{item_id}")
                task = test_orchestrator._on_agent_complete(item_id, result)
                completion_tasks.append(task)

            await asyncio.gather(*completion_tasks)

            # Verify all sessions were cleaned up
            assert len(test_orchestrator.sessions) == 0

    async def test_error_during_worktree_creation(
        self, test_orchestrator, test_item, mock_git_operations
    ):
        """Test error handling when worktree creation fails."""
        item_id = test_item["id"]

        # Mock worktree creation failure
        mock_git_operations['create_worktree'].side_effect = Exception("Git error: unable to create worktree")

        with pytest.raises(Exception, match="Git error: unable to create worktree"):
            await test_orchestrator.start_agent(item_id)

        # Verify item state wasn't corrupted
        async with test_orchestrator.db.connect() as conn:
            cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
            item = dict(await cursor.fetchone())

        # Item should still be in original state
        assert item["column_name"] == "todo"
        assert item["worktree_path"] is None


@pytest.mark.integration
class TestOrchestratorConcurrency:
    """Tests for concurrent orchestrator operations and edge cases."""

    async def test_rapid_cancel_and_restart(
        self, test_orchestrator, test_item, mock_git_operations
    ):
        """Test rapidly cancelling and restarting an agent."""
        item_id = test_item["id"]

        mock_session = AsyncMock()
        mock_session.cancel = AsyncMock()

        with patch.object(test_orchestrator, '_create_session', return_value=mock_session):
            # Start agent
            await test_orchestrator.start_agent(item_id)

            # Immediately cancel
            await test_orchestrator.cancel_agent(item_id)

            # Immediately restart
            await test_orchestrator.start_agent(item_id)

            # Verify final state is running
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

        mock_session = AsyncMock()
        with patch.object(test_orchestrator, '_create_session', return_value=mock_session):
            # Start agent
            await test_orchestrator.start_agent(item_id)

            # Verify agent is active
            assert item_id in test_orchestrator.sessions

            # Shutdown orchestrator
            await test_orchestrator.shutdown()

            # Verify all sessions were cancelled and cleaned up
            mock_session.cancel.assert_called_once()
            assert len(test_orchestrator.sessions) == 0
            assert len(test_orchestrator._agent_tasks) == 0