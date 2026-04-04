"""Workflow service for coordinating agent workflows and state transitions."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..agent.session import AgentResult
from .database_service import DatabaseService
from .git_service import GitService
from .notification_service import NotificationService
from .session_service import SessionService

logger = logging.getLogger(__name__)


class WorkflowService:
    """Coordinates workflows and state transitions between services."""

    def __init__(self, db_service: DatabaseService, git_service: GitService,
                 notification_service: NotificationService, session_service: SessionService):
        self.db = db_service
        self.git = git_service
        self.notifications = notification_service
        self.sessions = session_service

        # State for question/response handling
        self._clarify_events: Dict[str, asyncio.Event] = {}
        self._clarify_responses: Dict[str, str] = {}

        # Merge conflict retry counters (in-memory, per item_id)
        self._merge_retries: Dict[str, int] = {}

    async def start_agent(self, item_id: str) -> Dict[str, Any]:
        """Start an agent for an item. Creates worktree, launches agent."""
        # Clean up any existing session for this item
        await self.sessions.cleanup_session(item_id)

        # Get item and config
        item = await self.db.get_item(item_id)
        if not item:
            raise ValueError(f"Item {item_id} not found")

        config = await self.db.get_agent_config()

        # Setup git worktree
        worktree_path, branch_name, base_branch, base_commit = await self.git.create_or_reuse_worktree(
            item_id, item.get("worktree_path"), item.get("branch_name")
        )

        # Update item state (preserve existing base_commit if reusing worktree)
        update_kwargs = dict(
            column_name="doing",
            status="running",
            branch_name=branch_name,
            worktree_path=str(worktree_path),
            base_branch=base_branch,
        )
        if base_commit:
            update_kwargs["base_commit"] = base_commit
        item = await self.db.update_item(item_id, **update_kwargs)
        await self.notifications.broadcast_item_updated(item)

        await self._log_and_notify(item_id, "system", "Agent started")

        # Create session
        model = item.get("model") or config.get("model")
        session = await self.sessions.create_session(
            item_id, worktree_path, config, model,
            on_message=self._create_on_message_callback(item_id),
            on_tool_use=self._create_on_tool_use_callback(item_id),
            on_thinking=self._create_on_thinking_callback(item_id),
            on_complete=self._create_on_complete_callback(item_id),
            on_error=self._create_on_error_callback(item_id),
            on_clarify=self._create_on_clarify_callback(item_id),
            on_create_todo=self._create_on_create_todo_callback(item_id),
            on_create_epic=self._create_on_create_epic_callback(item_id),
            on_set_commit_message=self._create_on_set_commit_message_callback(item_id),
            on_request_command=self._create_on_request_command_callback(item_id),
            on_request_tool=self._create_on_request_tool_callback(item_id),
            on_view_board=self._create_on_view_board_callback(),
            on_delete_todo=self._create_on_delete_todo_callback(item_id),
        )

        # Build prompt and fetch attachments
        prompt = f"Task: {item['title']}\n\n{item['description']}"
        attachments = await self.db.get_attachments(item_id)
        if attachments:
            await self._log_and_notify(item_id, "system", f"Found {len(attachments)} image attachment(s) for agent")

        # Start session in background
        await self.sessions.start_session_task(item_id, session, prompt, attachments)

        return item

    async def start_copy_agent(self, item_id: str) -> Dict[str, Any]:
        """Copy a todo item and start the copy, leaving the original in todo."""
        # Verify source item exists and is in todo
        source_item = await self.db.get_item(item_id)
        if not source_item:
            raise ValueError(f"Item {item_id} not found")
        if source_item.get("column_name") != "todo":
            raise ValueError("Can only start-copy items in the todo column")

        # Copy the item (including attachments)
        new_item = await self.db.copy_item(item_id)
        await self.notifications.broadcast_item_created(new_item)

        # Start the copy
        return await self.start_agent(new_item["id"])

    async def cancel_agent(self, item_id: str) -> Dict[str, Any]:
        """Cancel a running agent."""
        await self.sessions.cleanup_session(item_id)

        await self._log_and_notify(item_id, "system", "Agent cancelled by user")
        item = await self.db.update_item(item_id, column_name="todo", status="cancelled")
        await self.notifications.broadcast_item_updated(item)
        return item

    async def pause_agent(self, item_id: str) -> Dict[str, Any]:
        """Pause a running agent — save session for later resumption."""
        session_id = await self.sessions.pause_session(item_id)

        update_kwargs: Dict[str, Any] = dict(status="paused")
        if session_id:
            update_kwargs["session_id"] = session_id

        item = await self.db.update_item(item_id, **update_kwargs)
        await self._log_and_notify(item_id, "system", "Agent paused by user")
        await self.notifications.broadcast_item_updated(item)
        return item

    async def resume_agent(self, item_id: str) -> Dict[str, Any]:
        """Resume a paused agent using its saved session."""
        item = await self.db.get_item(item_id)
        if not item:
            raise ValueError(f"Item {item_id} not found")

        resume_id = item.get("session_id")
        if resume_id:
            await self._log_and_notify(item_id, "system", f"Agent resuming session {resume_id[:8]}...")
        else:
            await self._log_and_notify(item_id, "system", "Agent resuming (no session to resume — starting fresh)")

        config = await self.db.get_agent_config()
        worktree_path = Path(item["worktree_path"])

        item = await self.db.update_item(item_id, status="running")
        await self.notifications.broadcast_item_updated(item)

        model = item.get("model") or config.get("model")
        session = await self.sessions.create_session(
            item_id, worktree_path, config, model,
            on_message=self._create_on_message_callback(item_id),
            on_tool_use=self._create_on_tool_use_callback(item_id),
            on_thinking=self._create_on_thinking_callback(item_id),
            on_complete=self._create_on_complete_callback(item_id),
            on_error=self._create_on_error_callback(item_id),
            on_clarify=self._create_on_clarify_callback(item_id),
            on_create_todo=self._create_on_create_todo_callback(item_id),
            on_create_epic=self._create_on_create_epic_callback(item_id),
            on_set_commit_message=self._create_on_set_commit_message_callback(item_id),
            on_request_command=self._create_on_request_command_callback(item_id),
            on_request_tool=self._create_on_request_tool_callback(item_id),
            on_view_board=self._create_on_view_board_callback(),
            on_delete_todo=self._create_on_delete_todo_callback(item_id),
        )

        prompt = f"Continue working on your task:\nTask: {item['title']}\n\n{item['description']}"
        attachments = await self.db.get_attachments(item_id)
        await self.sessions.start_session_task(item_id, session, prompt, attachments, resume_id)

        return item

    async def retry_agent(self, item_id: str) -> Dict[str, Any]:
        """Retry a failed agent — resume previous session if available."""
        await self.sessions.cleanup_session(item_id)

        item = await self.db.get_item(item_id)
        if not item:
            raise ValueError(f"Item {item_id} not found")

        # Ensure worktree exists
        worktree_path = Path(item["worktree_path"]) if item.get("worktree_path") else None
        if not worktree_path or not worktree_path.exists():
            branch_name = item.get("branch_name") or f"agent/{item_id}"
            worktree_path, _, _, _ = await self.git.create_or_reuse_worktree(item_id, None, branch_name)
            await self.db.update_item(
                item_id,
                branch_name=branch_name,
                worktree_path=str(worktree_path),
            )

        resume_id = item.get("session_id")
        if resume_id:
            await self._log_and_notify(item_id, "system", f"Agent resuming session {resume_id[:8]}...")
        else:
            await self._log_and_notify(item_id, "system", "Agent retrying (no session to resume)")

        # Re-read item to get updated worktree_path
        item = await self.db.get_item(item_id)
        config = await self.db.get_agent_config()
        worktree_path = Path(item["worktree_path"])

        # Update item state
        item = await self.db.update_item(item_id, column_name="doing", status="running")
        await self.notifications.broadcast_item_updated(item)

        # Create session and start with resume
        model = item.get("model") or config.get("model")
        session = await self.sessions.create_session(
            item_id, worktree_path, config, model,
            on_message=self._create_on_message_callback(item_id),
            on_tool_use=self._create_on_tool_use_callback(item_id),
            on_thinking=self._create_on_thinking_callback(item_id),
            on_complete=self._create_on_complete_callback(item_id),
            on_error=self._create_on_error_callback(item_id),
            on_clarify=self._create_on_clarify_callback(item_id),
            on_create_todo=self._create_on_create_todo_callback(item_id),
            on_create_epic=self._create_on_create_epic_callback(item_id),
            on_set_commit_message=self._create_on_set_commit_message_callback(item_id),
            on_request_command=self._create_on_request_command_callback(item_id),
            on_request_tool=self._create_on_request_tool_callback(item_id),
            on_view_board=self._create_on_view_board_callback(),
            on_delete_todo=self._create_on_delete_todo_callback(item_id),
        )

        prompt = f"Task: {item['title']}\n\n{item['description']}"
        attachments = await self.db.get_attachments(item_id)
        await self.sessions.start_session_task(item_id, session, prompt, attachments, resume_id)

        return item

    async def approve_item(self, item_id: str) -> Dict[str, Any]:
        """Approve a reviewed item — merge back into the base branch."""
        item = await self.db.get_item(item_id)
        if not item:
            raise ValueError(f"Item {item_id} not found")

        branch = item["branch_name"]
        base_branch = item.get("base_branch")
        worktree_path = Path(item["worktree_path"]) if item.get("worktree_path") else None
        commit_msg = item.get("commit_message")

        # Check if base repo has dirty files that overlap with the agent's changes
        from ..git.operations import run_git
        try:
            # Get locally modified tracked files (exclude untracked with no '??' prefix)
            status_output = await run_git(self.git.target_project, "status", "--porcelain")
            dirty_files = set()
            for line in status_output.strip().splitlines():
                if not line or line.startswith("??"):
                    continue  # skip untracked files
                # porcelain format: XY<space>filename (XY = 2 status chars)
                # Use --porcelain -z would be cleaner, but just find first non-space after pos 1
                rest = line[2:]  # skip XY status chars
                filepath = rest.lstrip(" ").split(" -> ")[-1].strip()
                if filepath:
                    dirty_files.add(filepath)

            if dirty_files and worktree_path:
                # Get files changed by the agent's branch (committed + uncommitted)
                base = base_branch or "main"
                agent_files = set()
                try:
                    # Committed changes vs base
                    committed = await run_git(
                        worktree_path, "diff", "--name-only", base, "HEAD")
                    agent_files.update(f.strip() for f in committed.strip().splitlines() if f.strip())
                except Exception:
                    pass
                try:
                    # Uncommitted changes in the worktree
                    uncommitted = await run_git(worktree_path, "diff", "--name-only")
                    agent_files.update(f.strip() for f in uncommitted.strip().splitlines() if f.strip())
                    # Staged but not committed
                    staged = await run_git(worktree_path, "diff", "--name-only", "--cached")
                    agent_files.update(f.strip() for f in staged.strip().splitlines() if f.strip())
                except Exception as e:
                    logger.warning(f"Failed to get worktree uncommitted files: {e}")

                overlap = dirty_files & agent_files
                if overlap:
                    file_list = ", ".join(sorted(overlap)[:5])
                    if len(overlap) > 5:
                        file_list += f" (+{len(overlap) - 5} more)"
                    await self._log_and_notify(item_id, "system",
                        f"Cannot merge — conflicting uncommitted changes in: {file_list}")
                    item = await self.db.update_item(item_id,
                        column_name="questions", status="merge_blocked")
                    await self.notifications.broadcast_item_updated(item)
                    await self.notifications.ws_manager.broadcast("merge_blocked", {
                        "item_id": item_id,
                        "message": f"Cannot merge because these files have uncommitted changes "
                                   f"in the target repo: {file_list}. "
                                   f"Please commit or stash your changes, then try again.",
                    })
                    return item
        except Exception as e:
            logger.warning(f"Failed to check repo status: {e}")

        success, message = await self.git.merge_agent_work(
            branch, base_branch, worktree_path, commit_msg
        )

        if success:
            self._merge_retries.pop(item_id, None)
            merge_sha = message  # on success, message contains the merge commit SHA
            target = base_branch or "current branch"
            short_sha = merge_sha[:8] if merge_sha else ""
            await self._log_and_notify(item_id, "system",
                f"Merged {branch} into {target} ({short_sha})")

            # Clean up worktree
            if worktree_path:
                await self.git.cleanup_worktree_and_branch(worktree_path, branch)

            item = await self.db.update_item(
                item_id,
                column_name="done",
                status=None,
                worktree_path=None,
                merge_commit=merge_sha,
            )

            await self._notify_and_auto_start_dependents(item_id)
        else:
            await self._log_and_notify(item_id, "system",
                f"Merge failed — {message[:200]}. Attempting auto-rebase...")

            # Phase 1: Try automatic rebase before resorting to agent restart
            if worktree_path:
                from ..git.operations import run_git, get_current_branch

                # Commit any uncommitted work first
                from ..git.operations import commit_worktree_changes
                try:
                    await commit_worktree_changes(worktree_path, commit_msg or f"Agent work on {branch}")
                except Exception:
                    pass

                base = base_branch or await get_current_branch(self.git.target_project)
                rebase_ok, rebase_msg = await self.git.rebase_onto_base(worktree_path, base)

                if rebase_ok:
                    await self._log_and_notify(item_id, "system",
                        f"Auto-rebase onto {base} succeeded, retrying merge")

                    # Retry the merge after successful rebase
                    success2, message2 = await self.git.merge_agent_work(
                        branch, base_branch, worktree_path, commit_msg
                    )
                    if success2:
                        self._merge_retries.pop(item_id, None)
                        merge_sha = message2
                        target = base_branch or "current branch"
                        short_sha = merge_sha[:8] if merge_sha else ""
                        await self._log_and_notify(item_id, "system",
                            f"Merged {branch} into {target} ({short_sha}) after rebase")

                        if worktree_path:
                            await self.git.cleanup_worktree_and_branch(worktree_path, branch)

                        item = await self.db.update_item(
                            item_id, column_name="done", status=None,
                            worktree_path=None, merge_commit=merge_sha,
                        )

                        await self._notify_and_auto_start_dependents(item_id)
                        await self.notifications.broadcast_item_updated(item)
                        return item
                    else:
                        await self._log_and_notify(item_id, "system",
                            f"Merge still failed after rebase: {message2[:200]}")
                else:
                    await self._log_and_notify(item_id, "system",
                        f"Auto-rebase failed ({rebase_msg[:100]}), falling back to agent restart")

            # Phase 2: Rebase didn't work — fall back to agent restart with diff
            # Check retry counter to prevent infinite loops
            merge_retries = self._merge_retries.get(item_id, 0)
            MAX_MERGE_RETRIES = 2
            if merge_retries >= MAX_MERGE_RETRIES:
                await self._log_and_notify(item_id, "system",
                    f"Conflict resolution failed after {merge_retries} retries. Manual intervention needed.")
                item = await self.db.update_item(item_id, status="conflict")
                await self.notifications.broadcast_item_updated(item)
                return item

            # Capture the agent's work as a diff before resetting
            try:
                from ..git.operations import run_git, get_current_branch
                agent_diff = await run_git(worktree_path, "diff", "HEAD~1", "HEAD")
                if not agent_diff.strip():
                    # Try diff against base
                    base = base_branch or await get_current_branch(self.git.target_project)
                    agent_diff = await run_git(worktree_path, "diff", base, "HEAD")
            except Exception:
                agent_diff = ""

            if agent_diff and worktree_path:
                # Reset worktree to latest base branch
                try:
                    base = base_branch or await get_current_branch(self.git.target_project)
                    await run_git(worktree_path, "fetch", "origin", base)
                    await run_git(worktree_path, "reset", "--hard", base)
                    await self._log_and_notify(item_id, "system",
                        f"Reset worktree to latest {base}, restarting agent with previous diff "
                        f"(retry {merge_retries + 1}/{MAX_MERGE_RETRIES})")
                except Exception as e:
                    logger.warning(f"Failed to reset worktree: {e}")

                # Increment retry counter and restart agent with the diff as context
                self._merge_retries[item_id] = merge_retries + 1
                item = await self.db.update_item(
                    item_id, column_name="doing", status="resolving_conflicts")
                await self.notifications.broadcast_item_updated(item)

                config = await self.db.get_agent_config()
                model = item.get("model") or config.get("model")
                session = await self.sessions.create_session(
                    item_id, worktree_path, config, model,
                    on_message=self._create_on_message_callback(item_id),
                    on_tool_use=self._create_on_tool_use_callback(item_id),
                    on_thinking=self._create_on_thinking_callback(item_id),
                    on_complete=self._create_on_complete_callback(item_id),
                    on_error=self._create_on_error_callback(item_id),
                    on_clarify=self._create_on_clarify_callback(item_id),
                    on_create_todo=self._create_on_create_todo_callback(item_id),
            on_create_epic=self._create_on_create_epic_callback(item_id),
                    on_set_commit_message=self._create_on_set_commit_message_callback(item_id),
                    on_request_command=self._create_on_request_command_callback(item_id),
                    on_request_tool=self._create_on_request_tool_callback(item_id),
                    on_view_board=self._create_on_view_board_callback(),
                    on_delete_todo=self._create_on_delete_todo_callback(item_id),
                )

                conflict_prompt = (
                    f"Your previous changes caused a merge conflict. The base branch has been updated.\n\n"
                    f"Here is the diff of your previous work — please reapply these changes to the "
                    f"updated codebase, resolving any conflicts:\n\n```diff\n{agent_diff}\n```\n\n"
                    f"Original task: {item['title']}\n\n{item['description']}"
                )
                await self.sessions.start_session_task(item_id, session, conflict_prompt)
                return item

            # Fallback: no diff captured, show conflict status
            item = await self.db.update_item(item_id, status="conflict")

        await self.notifications.broadcast_item_updated(item)
        return item

    async def _notify_and_auto_start_dependents(self, resolved_item_id: str):
        """Notify dependents that a dependency was resolved, and auto-start if configured."""
        dependent_ids = await self.db.get_dependent_items(resolved_item_id)
        if not dependent_ids:
            return

        await self.notifications.ws_manager.broadcast("dependencies_resolved", {
            "resolved_item_id": resolved_item_id,
            "dependent_item_ids": dependent_ids,
        })

        # Auto-start any newly unblocked items that have auto_start enabled
        for dep_id in dependent_ids:
            dep_item = await self.db.get_item(dep_id)
            if not dep_item:
                continue
            if not dep_item.get("auto_start"):
                continue
            if dep_item.get("column_name") != "todo":
                continue
            # Check if ALL dependencies are now resolved (not just this one)
            if await self.db.is_item_blocked(dep_id):
                continue
            await self._log_and_notify(dep_id, "system",
                "All dependencies resolved — auto-starting agent")
            try:
                await self.start_agent(dep_id)
            except Exception as e:
                logger.warning(f"Auto-start failed for {dep_id}: {e}")

    async def request_changes(self, item_id: str, comments: List[str]) -> Dict[str, Any]:
        """Send review comments back to the agent."""
        await self.sessions.cleanup_session(item_id)

        # Store comments and get item
        await self.db.store_review_comments(item_id, comments)
        item = await self.db.get_item(item_id)

        # Build feedback prompt
        feedback = "Review feedback — please address these comments:\n\n"
        feedback += "\n".join(f"- {c}" for c in comments)

        await self._log_and_notify(item_id, "user_action", f"Review changes requested: {'; '.join(comments)}")

        # Update item to doing
        item = await self.db.update_item(item_id, column_name="doing", status="running")
        await self.notifications.broadcast_item_updated(item)

        # Start new agent session with feedback
        config = await self.db.get_agent_config()
        worktree_path = Path(item["worktree_path"])

        session = await self.sessions.create_session(
            item_id, worktree_path, config,
            on_message=self._create_on_message_callback(item_id),
            on_tool_use=self._create_on_tool_use_callback(item_id),
            on_thinking=self._create_on_thinking_callback(item_id),
            on_complete=self._create_on_complete_callback(item_id),
            on_error=self._create_on_error_callback(item_id),
            on_clarify=self._create_on_clarify_callback(item_id),
            on_create_todo=self._create_on_create_todo_callback(item_id),
            on_create_epic=self._create_on_create_epic_callback(item_id),
            on_set_commit_message=self._create_on_set_commit_message_callback(item_id),
            on_request_command=self._create_on_request_command_callback(item_id),
            on_request_tool=self._create_on_request_tool_callback(item_id),
            on_view_board=self._create_on_view_board_callback(),
            on_delete_todo=self._create_on_delete_todo_callback(item_id),
        )

        # Fetch attachments for context
        attachments = await self.db.get_attachments(item_id)

        # Resume conversation with feedback
        resume_id = item.get("session_id")
        await self.sessions.start_session_task(item_id, session, feedback, attachments, resume_id)

        return item

    async def cancel_review(self, item_id: str) -> Dict[str, Any]:
        """Cancel a review - discard changes and move item back to todo."""
        await self.sessions.cleanup_session(item_id)

        item = await self.db.get_item(item_id)
        if not item:
            raise ValueError(f"Item {item_id} not found")

        # Clean up worktree
        await self.git.cleanup_item_resources(item.get("worktree_path"), item.get("branch_name"))
        await self._log_and_notify(item_id, "user_action", "Review cancelled - work discarded")

        # Move item back to todo
        item = await self.db.update_item(
            item_id,
            column_name="todo",
            status=None,
            worktree_path=None,
        )
        await self.notifications.broadcast_item_updated(item)
        return item

    async def submit_clarification(self, item_id: str, response: str) -> Dict[str, Any]:
        """Submit a question response to a waiting agent."""
        await self.db.update_clarification_response(item_id, response)

        # Signal the waiting clarify callback
        self._clarify_responses[item_id] = response
        event = self._clarify_events.get(item_id)
        if event:
            event.set()

        return {"ok": True}

    async def delete_item(self, item_id: str) -> Dict[str, Any]:
        """Delete an item and clean up all associated resources."""
        await self.sessions.cleanup_session(item_id)

        # Delete from database and get info for cleanup
        item = await self.db.delete_item_and_related(item_id)

        # Clean up git resources
        if item:
            await self.git.cleanup_item_resources(item.get("worktree_path"), item.get("branch_name"))

        # Broadcast deletion
        await self.notifications.broadcast_item_deleted(item_id)
        return {"ok": True}

    async def shutdown(self):
        """Gracefully stop all running agents."""
        await self.sessions.cleanup_all_sessions()

    # Callback creators
    def _create_on_message_callback(self, item_id: str):
        async def on_message(text: str):
            await self._log_and_notify(item_id, "agent_message", text)
        return on_message

    def _create_on_tool_use_callback(self, item_id: str):
        async def on_tool_use(name: str, inp: Dict[str, Any]):
            formatted = self.notifications.format_tool_use(name, inp)
            await self._log_and_notify(item_id, "tool_use", formatted, json.dumps(inp))
        return on_tool_use

    def _create_on_thinking_callback(self, item_id: str):
        async def on_thinking(text: str):
            await self._log_and_notify(item_id, "thinking", text)
        return on_thinking

    def _create_on_complete_callback(self, item_id: str):
        async def on_complete(result: AgentResult):
            # Save token usage
            await self.db.save_token_usage(item_id, result)

            if result.success:
                # Create log message with cost and token info
                log_message = self.notifications.format_completion_log(
                    result.cost_usd, result.total_tokens, result.input_tokens, result.output_tokens
                )
                await self._log_and_notify(item_id, "system", log_message)

                # Use commit message from session
                commit_message = self.sessions.get_commit_message(item_id)

                update_kwargs = dict(
                    column_name="review",
                    status=None,
                    session_id=result.session_id,
                )
                if commit_message:
                    update_kwargs["commit_message"] = commit_message

                item = await self.db.update_item(item_id, **update_kwargs)
                await self.notifications.broadcast_item_updated(item, source="agent")
            else:
                await self._log_and_notify(item_id, "error", f"Agent failed: {result.error}")
                item = await self.db.update_item(item_id, status="failed", session_id=result.session_id)
                await self.notifications.broadcast_item_updated(item, source="agent")
                self._add_failure_notification(item_id, result.error)

            # Remove finished session from tracking so it no longer counts as active
            self.sessions.remove_session(item_id)

        return on_complete

    def _create_on_error_callback(self, item_id: str):
        async def on_error(error: str):
            await self._log_and_notify(item_id, "error", f"Agent error: {error}")
            item = await self.db.update_item(item_id, status="failed")
            await self.notifications.broadcast_item_updated(item, source="agent")
            self._add_failure_notification(item_id, error)
            # Remove finished session from tracking so it no longer counts as active
            self.sessions.remove_session(item_id)
        return on_error

    def _add_failure_notification(self, item_id: str, error: str):
        """Add a system notification for agent failures."""
        try:
            from ..web.routes import add_notification
            short_error = error[:200] if len(error) > 200 else error
            add_notification("error", f"Agent {item_id[:8]} failed: {short_error}", source=f"agent:{item_id[:8]}")
        except Exception:
            pass

    def _create_on_clarify_callback(self, item_id: str):
        async def on_clarify(prompt: str, choices: Optional[List[str]]) -> str:
            # Move item to questions
            item = await self.db.update_item(item_id, column_name="questions", status=None)
            await self.notifications.broadcast_item_updated(item, source="agent")
            await self._log_and_notify(item_id, "system", f"Agent has a question: {prompt}")

            # Store clarification
            await self.db.store_clarification(item_id, prompt, choices)

            # Broadcast to frontend
            await self.notifications.broadcast_clarification_requested(item_id, prompt, choices)

            # Wait for user response
            event = asyncio.Event()
            self._clarify_events[item_id] = event
            await event.wait()

            response = self._clarify_responses.pop(item_id, "")
            self._clarify_events.pop(item_id, None)

            # Move back to doing
            item = await self.db.update_item(item_id, column_name="doing", status="running")
            await self.notifications.broadcast_item_updated(item)
            await self._log_and_notify(item_id, "system", f"User responded: {response}")

            return response

        return on_clarify

    def _create_on_request_command_callback(self, item_id: str):
        async def on_request_command(command: str, reason: str) -> str:
            item = await self.db.update_item(
                item_id, column_name="questions", status=None
            )
            await self.notifications.broadcast_item_updated(item, source="agent")
            await self._log_and_notify(
                item_id, "system",
                f"Agent requests permission to run '{command}': {reason}"
            )

            # Store as clarification so it persists and can be retrieved on card click
            prompt = f"__permission_request__|{command}|{reason}"
            await self.db.store_clarification(item_id, prompt, None)

            await self.notifications.ws_manager.broadcast(
                "permission_requested",
                {
                    "item_id": item_id,
                    "command": command,
                    "reason": reason,
                },
            )

            event = asyncio.Event()
            self._clarify_events[item_id] = event
            await event.wait()

            response = self._clarify_responses.pop(item_id, "denied")
            self._clarify_events.pop(item_id, None)

            if response == "approved":
                await self.db.save_allowed_command(command)
                await self._log_and_notify(
                    item_id, "system",
                    f"Command '{command}' approved — restarting session with updated permissions"
                )

                # Get session_id from the running session for resume
                old_session = self.sessions.sessions.get(item_id)
                resume_id = None
                if old_session:
                    resume_id = getattr(old_session, 'current_session_id', None)

                # Schedule restart as a separate task — we can't cleanup the
                # current session from inside it (we're running in its task).
                item = await self.db.get_item(item_id)
                asyncio.create_task(
                    self._restart_session_with_new_permissions(
                        item_id, command, resume_id, item
                    )
                )

                # Return approved so the MCP tool handler exits cleanly.
                # The session will be killed and restarted by the task above.
                return "approved"
            else:
                await self._log_and_notify(
                    item_id, "system",
                    f"Command '{command}' access denied"
                )

            item = await self.db.update_item(
                item_id, column_name="doing", status="running"
            )
            await self.notifications.broadcast_item_updated(item)

            return response

        return on_request_command

    def _create_on_request_tool_callback(self, item_id: str):
        async def on_request_tool(tool_name: str, reason: str) -> str:
            item = await self.db.update_item(
                item_id, column_name="questions", status=None
            )
            await self.notifications.broadcast_item_updated(item, source="agent")
            await self._log_and_notify(
                item_id, "system",
                f"Agent requests permission to use '{tool_name}': {reason}"
            )

            # Store as clarification so it persists and can be retrieved on card click
            prompt = f"__tool_request__|{tool_name}|{reason}"
            await self.db.store_clarification(item_id, prompt, None)

            await self.notifications.ws_manager.broadcast(
                "tool_permission_requested",
                {
                    "item_id": item_id,
                    "tool_name": tool_name,
                    "reason": reason,
                },
            )

            event = asyncio.Event()
            self._clarify_events[item_id] = event
            await event.wait()

            response = self._clarify_responses.pop(item_id, "denied")
            self._clarify_events.pop(item_id, None)

            if response == "approved":
                await self.db.save_allowed_builtin_tool(tool_name)
                await self._log_and_notify(
                    item_id, "system",
                    f"Tool '{tool_name}' approved — restarting session with updated permissions"
                )

                old_session = self.sessions.sessions.get(item_id)
                resume_id = None
                if old_session:
                    resume_id = getattr(old_session, 'current_session_id', None)

                item = await self.db.get_item(item_id)
                asyncio.create_task(
                    self._restart_session_with_new_permissions(
                        item_id, tool_name, resume_id, item
                    )
                )

                return "approved"
            else:
                await self._log_and_notify(
                    item_id, "system",
                    f"Tool '{tool_name}' access denied"
                )

            item = await self.db.update_item(
                item_id, column_name="doing", status="running"
            )
            await self.notifications.broadcast_item_updated(item)

            return response

        return on_request_tool

    def _create_on_create_todo_callback(self, item_id: str):
        async def on_create_todo(title: str, description: str, epic_id: str = None, requires: list[str] = None) -> Dict[str, Any]:
            item = await self.db.create_todo_item(title, description, epic_id)
            if requires:
                await self.db.set_item_dependencies(item["id"], requires)
            await self._log_and_notify(item_id, "system", f"Created todo item: {title}")
            await self.notifications.broadcast_item_created(item)
            if requires:
                blocked_status = await self.db.get_all_blocked_status()
                await self.notifications.ws_manager.broadcast("blocked_status_changed", {
                    "blocked": blocked_status,
                })
            return item
        return on_create_todo

    def _create_on_create_epic_callback(self, item_id: str):
        async def on_create_epic(title: str, color: str) -> Dict[str, Any]:
            epic = await self.db.create_epic(title, color)
            await self._log_and_notify(item_id, "system", f"Created epic: {title}")
            await self.notifications.broadcast_epic_created(epic)
            return epic
        return on_create_epic

    def _create_on_delete_todo_callback(self, item_id: str):
        async def on_delete_todo(target_id: str) -> str:
            # Only allow deleting items in the todo column
            target = await self.db.get_item(target_id)
            if not target:
                return f"Item '{target_id}' not found."
            if target["column_name"] != "todo":
                return f"Cannot delete item '{target['title']}' — it is in the '{target['column_name']}' column. Only todo items can be deleted."
            deleted = await self.db.delete_item_and_related(target_id)
            if deleted:
                await self._log_and_notify(item_id, "system", f"Deleted todo item: {deleted['title']}")
                await self.notifications.broadcast_item_deleted(target_id)
                return f"Deleted todo item: {deleted['title']}"
            return f"Failed to delete item '{target_id}'."
        return on_delete_todo

    def _create_on_set_commit_message_callback(self, item_id: str):
        async def on_set_commit_message(message: str) -> str:
            result = self.sessions.set_commit_message(item_id, message)
            await self._log_and_notify(item_id, "system", f"Commit message set: {message}")
            return result
        return on_set_commit_message

    def _create_on_view_board_callback(self):
        async def on_view_board() -> str:
            from ..config import COLUMNS
            items = await self.db.get_all_items()
            epics = await self.db.get_epics()
            epic_map = {e["id"]: e["title"] for e in epics}

            # Build dependency map: item_id -> list of required item IDs
            dep_map = {}
            for item in items:
                deps = await self.db.get_item_dependencies(item["id"])
                if deps:
                    dep_map[item["id"]] = deps

            # Group by column
            by_column = {}
            for item in items:
                col = item["column_name"]
                by_column.setdefault(col, []).append(item)

            lines = []

            # Show available epics
            if epics:
                lines.append("## Epics")
                for epic in epics:
                    lines.append(f"- [{epic['id']}] {epic['title']} (color: {epic.get('color', 'blue')})")
                lines.append("")

            for col in COLUMNS:
                col_id = col["id"]
                col_items = by_column.get(col_id, [])
                lines.append(f"## {col['label']} ({len(col_items)})")
                if col_items:
                    for item in col_items:
                        status = f" [{item['status']}]" if item.get("status") else ""
                        epic_text = f" [Epic: {epic_map.get(item.get('epic_id', ''), '')}]" if item.get('epic_id') else ""
                        deps = dep_map.get(item["id"], [])
                        dep_text = f" [requires: {', '.join(d['id'] for d in deps)}]" if deps else ""
                        lines.append(f"- [{item['id']}] {item['title']}{status}{epic_text}{dep_text}")
                else:
                    lines.append("  (empty)")
                lines.append("")
            return "\n".join(lines)
        return on_view_board

    async def _restart_session_with_new_permissions(self, item_id: str, command: str, resume_id: str | None, item: Dict[str, Any] | None = None):
        """Restart an agent session with updated allowed commands.

        Runs as a separate task so the old session's MCP handler can exit cleanly.
        """
        try:
            # Brief delay to let the MCP tool response propagate
            await asyncio.sleep(0.5)

            # Cancel the old session
            await self.sessions.cleanup_session(item_id)

            # Restart with updated config
            item = await self.db.get_item(item_id)
            if not item:
                return

            item = await self.db.update_item(
                item_id, column_name="doing", status="running"
            )
            await self.notifications.broadcast_item_updated(item)

            config = await self.db.get_agent_config()
            model = item.get("model") or config.get("model")
            worktree_path = Path(item["worktree_path"])
            new_session = await self.sessions.create_session(
                item_id, worktree_path, config, model,
                on_message=self._create_on_message_callback(item_id),
                on_tool_use=self._create_on_tool_use_callback(item_id),
                on_thinking=self._create_on_thinking_callback(item_id),
                on_complete=self._create_on_complete_callback(item_id),
                on_error=self._create_on_error_callback(item_id),
                on_clarify=self._create_on_clarify_callback(item_id),
                on_create_todo=self._create_on_create_todo_callback(item_id),
            on_create_epic=self._create_on_create_epic_callback(item_id),
                on_set_commit_message=self._create_on_set_commit_message_callback(item_id),
                on_request_command=self._create_on_request_command_callback(item_id),
                on_request_tool=self._create_on_request_tool_callback(item_id),
                on_view_board=self._create_on_view_board_callback(),
                on_delete_todo=self._create_on_delete_todo_callback(item_id),
            )

            # Include original task so agent knows what to do even without resume
            task_title = (item or {}).get("title", "")
            task_desc = (item or {}).get("description", "")
            restart_prompt = (
                f"Permission for '{command}' was granted. "
                f"You can now run {command} commands.\n\n"
                f"Continue with your original task:\n"
                f"Task: {task_title}\n\n{task_desc}"
            )
            await self.sessions.start_session_task(
                item_id, new_session, restart_prompt, None, resume_id
            )
        except Exception as e:
            logger.error(f"Failed to restart session for {item_id}: {e}")
            await self._log_and_notify(
                item_id, "system", f"Failed to restart session: {e}"
            )

    async def _log_and_notify(self, item_id: str, entry_type: str, content: str, metadata: Optional[str] = None):
        """Log entry to database and broadcast notification."""
        await self.db.log_entry(item_id, entry_type, content, metadata)
        await self.notifications.broadcast_agent_log(item_id, entry_type, content)