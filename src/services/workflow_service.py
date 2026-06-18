"""Workflow service for coordinating agent workflows and state transitions."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..agent.review_agent import run_auto_review
from ..agent.session import AgentResult
from ..constants import (
    AUTO_APPROVE_DIRECT,
    AUTO_APPROVE_MODES,
    AUTO_APPROVE_OFF,
    AUTO_APPROVE_REVIEW,
)
from ..domain.item_state import Event, ItemState, UnknownStateEncoding, from_columns
from ..repositories.epic_repository import EpicRepository
from ..repositories.item_repository import ItemRepository
from .database_service import DatabaseService
from .git_service import GitService
from .notification_service import NotificationService
from .session_service import SessionService

logger = logging.getLogger(__name__)

# Hard cap on auto-review return-trips before falling back to manual review.
_MAX_AUTO_APPROVE_RETRIES = 3


class WorkflowService:
    """Coordinates workflows and state transitions between services."""

    def __init__(self, db_service: DatabaseService, git_service: GitService,
                 notification_service: NotificationService, session_service: SessionService,
                 data_dir: Path | None = None,
                 item_repository: ItemRepository | None = None,
                 epic_repository: EpicRepository | None = None,
                 graph_service=None):
        self.db = db_service
        self.graph_service = graph_service
        self.git = git_service
        self.notifications = notification_service
        self.sessions = session_service
        self.data_dir = data_dir
        # Repo facades. Defaulted so existing constructors keep working;
        # orchestrator passes its own instances.
        self.items = item_repository or ItemRepository(db_service)
        self.epics = epic_repository or EpicRepository(db_service)

        # State for question/response handling
        self._clarify_events: Dict[str, asyncio.Event] = {}
        self._clarify_responses: Dict[str, str] = {}

        # Merge conflict retry counters (in-memory, per item_id)
        self._merge_retries: Dict[str, int] = {}

        # Auto-approve review-cycle counters (in-memory, per item_id).
        # Capped at _MAX_AUTO_APPROVE_RETRIES; reset on approval / cancellation
        # / deletion. Resets across dashboard restarts (acceptable — restart
        # implies the user is back in the loop).
        self._auto_approve_retries: Dict[str, int] = {}

        # Last assistant text per item, captured by on_message. Fed to the
        # review agent so it sees the implementing agent's final summary.
        self._last_agent_message: Dict[str, str] = {}

        # Track which items are running with YOLO mode (bash_yolo=True)
        self._yolo_items: set = set()

        # Track items currently being inspected by the auto-review agent.
        # Items in this set are sitting in the review column with status=None
        # (DB-wise no different from a normal review item) but a separate
        # read-only Claude session is actively examining their diff. The UI
        # subscribes to `auto_review_changed` to render a "Reviewing…" badge.
        self._auto_reviewing: set = set()

    async def _count_running_agents(self) -> int:
        """Count how many agents are currently running (not queued)."""
        return len(self.sessions.sessions)

    def _item_session_kwargs(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Per-item extra kwargs for SessionService.create_session.

        Always carries the item's `use_chrome` flag; adds multi-repo read-scope
        kwargs when in multi-repo mode. Callers can splat it either way.
        Uses getattr so mocks that don't expose `repos` (e.g. MagicMock spec'd
        against GitService before this attribute existed) behave as single-mode.
        """
        kwargs: Dict[str, Any] = {
            "use_chrome": bool(item.get("use_chrome")) if item else False,
            # Self-view tool: lets the agent fetch its own card (incl. its item ID
            # for `requires`) instead of guessing from view_board. Threaded here so
            # it reaches every create_session call site in one place.
            "on_who_am_i": self._create_on_who_am_i_callback(item.get("id") if item else None),
        }
        repos = getattr(self.git, "repos", None)
        if not repos:
            return kwargs
        item_repo = item.get("repo") if item else None
        # Read scope: all known repos except the one the item is actively working on
        # (the agent's own repo is reached via the worktree, not as a sibling).
        sibling_paths = [
            self.git.base_repo_path(r) for r in repos if r != item_repo
        ]
        kwargs.update({
            "workspace_root": self.git.target_project,
            "sibling_repo_paths": sibling_paths,
            "item_repo_name": item_repo,
        })
        return kwargs

    async def _is_at_wip_limit(self) -> bool:
        """Check if the number of running agents has reached the WIP limit."""
        config = await self.db.get_agent_config()
        wip_limit = config.get("wip_limit", 0)
        if wip_limit <= 0:
            return False
        running = await self._count_running_agents()
        return running >= wip_limit

    async def _enqueue_item(self, item_id: str) -> Dict[str, Any]:
        """Place an item in the doing column with queued status."""
        item = await self.items.transition(item_id, Event.ENQUEUE)
        await self.notifications.broadcast_item_updated(item)
        await self._log_and_notify(item_id, "system",
            "WIP limit reached — item queued, will auto-start when a slot opens")
        return item

    async def process_queue(self) -> None:
        """Start the next queued item(s) if slots are available."""
        config = await self.db.get_agent_config()
        wip_limit = config.get("wip_limit", 0)
        if wip_limit <= 0:
            return  # No limit — nothing to dequeue

        running = await self._count_running_agents()
        available_slots = wip_limit - running
        if available_slots <= 0:
            return

        # Get queued items ordered by position (top of column = first)
        queued_items = await self.items.list_queued(limit=available_slots)
        for item in queued_items:
            try:
                await self._start_agent_internal(item["id"])
            except Exception as e:
                logger.warning(f"Failed to dequeue item {item['id']}: {e}")

    async def start_agent(self, item_id: str) -> Dict[str, Any]:
        """Start an agent for an item. Creates worktree, launches agent.
        If WIP limit is reached, the item is queued instead."""
        # Check WIP limit before starting
        if await self._is_at_wip_limit():
            return await self._enqueue_item(item_id)

        return await self._start_agent_internal(item_id)

    async def _start_agent_internal(self, item_id: str) -> Dict[str, Any]:
        """Actually start the agent (bypasses WIP limit check)."""
        # Clean up any existing session for this item
        await self.sessions.cleanup_session(item_id)

        # Get item and config
        item = await self.items.get_or_raise(item_id)

        config = await self.db.get_agent_config()

        # Setup git worktree
        worktree_path, branch_name, base_branch, base_commit = await self.git.create_or_reuse_worktree(
            item_id, item.get("worktree_path"), item.get("branch_name"),
            repo=item.get("repo"),
        )

        # Update item state. Both base_branch and base_commit are only set
        # on first creation — on the reuse paths create_or_reuse_worktree
        # returns None so we don't overwrite whatever was originally recorded
        # (which would silently change the merge target).
        extras: Dict[str, Any] = dict(
            branch_name=branch_name,
            worktree_path=str(worktree_path),
        )
        if base_branch:
            extras["base_branch"] = base_branch
        if base_commit:
            extras["base_commit"] = base_commit
        item = await self.items.transition(item_id, Event.START, **extras)
        await self.notifications.broadcast_item_updated(item)

        await self._log_and_notify(item_id, "system", "Agent started")

        # Track YOLO mode for this item
        is_yolo = config.get("bash_yolo", False)
        if is_yolo:
            self._yolo_items.add(item_id)
            await self._log_and_notify(item_id, "yolo_command",
                "⚠️ **YOLO mode active** — all bash commands bypass permission checks")
            await self.notifications.ws_manager.broadcast("yolo_mode_changed", {
                "item_id": item_id, "active": True,
            })
        else:
            self._yolo_items.discard(item_id)

        # Create session — validate Ollama model availability first
        model = item.get("model") or config.get("model")
        if model and not model.startswith("claude-") and config.get("ollama_enabled"):
            model = await self._validate_ollama_model(item_id, model, config)
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
            on_graph_query=self._create_on_graph_query_callback(),
            on_delete_todo=self._create_on_delete_todo_callback(item_id),
            on_create_shortcut=self._create_on_create_shortcut_callback(item_id),
            **self._item_session_kwargs(item),
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

        # Clean up YOLO tracking
        if item_id in self._yolo_items:
            self._yolo_items.discard(item_id)
            await self.notifications.ws_manager.broadcast("yolo_mode_changed", {
                "item_id": item_id, "active": False,
            })

        # Cancelling halts any in-flight auto-approve cycle for this item.
        self._auto_approve_retries.pop(item_id, None)

        await self._log_and_notify(item_id, "system", "Agent cancelled by user")
        item = await self.items.transition(item_id, Event.CANCEL)
        await self.notifications.broadcast_item_updated(item)

        # A slot may have opened — process the queue
        await self.process_queue()

        return item

    async def pause_agent(
        self, item_id: str, message: Optional[str] = None
    ) -> Dict[str, Any]:
        """Pause a running agent — save session for later resumption.

        If ``message`` is supplied, it's stored on the item and prepended to
        the resume prompt the next time the agent runs (e.g. asking it to
        investigate a different approach).
        """
        session_id = await self.sessions.pause_session(item_id)

        extras: Dict[str, Any] = {}
        if session_id:
            extras["session_id"] = session_id
        if message is not None:
            # Store None when blank so we don't carry empty strings around.
            extras["pause_message"] = message.strip() or None
        item = await self.items.transition(item_id, Event.PAUSE, **extras)

        log_msg = "Agent paused by user"
        if extras.get("pause_message"):
            log_msg += f" with note: {extras['pause_message']}"
        await self._log_and_notify(item_id, "system", log_msg)
        await self.notifications.broadcast_item_updated(item)
        return item

    async def resume_agent(
        self, item_id: str, message: Optional[str] = None
    ) -> Dict[str, Any]:
        """Resume a paused agent using its saved session.

        If ``message`` is supplied, it's used as the resume note (taking
        precedence over any ``pause_message`` previously stored on the item).
        Empty/whitespace-only messages fall back to the stored note, if any.
        """
        item = await self.items.get_or_raise(item_id)

        # The caller (work-log "Continue" form) may supply a fresh note. If
        # they don't, fall back to whatever the agent was paused with — both
        # are surfaced the same way: prepended to the resume prompt and then
        # cleared on the transition so a subsequent cycle starts clean.
        submitted = (message or "").strip()
        stored = (item.get("pause_message") or "").strip()
        pause_message = submitted or stored

        resume_id = item.get("session_id")
        if resume_id:
            await self._log_and_notify(item_id, "system", f"Agent resuming session {resume_id[:8]}...")
        else:
            await self._log_and_notify(item_id, "system", "Agent resuming (no session to resume — starting fresh)")
        if pause_message:
            await self._log_and_notify(
                item_id, "user_action", f"Resume note from user: {pause_message}"
            )

        config = await self.db.get_agent_config()
        worktree_path = Path(item["worktree_path"])

        # Track YOLO mode for resumed agent
        is_yolo = config.get("bash_yolo", False)
        if is_yolo:
            self._yolo_items.add(item_id)
            await self.notifications.ws_manager.broadcast("yolo_mode_changed", {
                "item_id": item_id, "active": True,
            })
        else:
            self._yolo_items.discard(item_id)

        # Clear pause_message on the same write that performs the transition
        # so the note is consumed exactly once.
        resume_extras: Dict[str, Any] = {}
        if pause_message or item.get("pause_message"):
            resume_extras["pause_message"] = None
        item = await self.items.transition(item_id, Event.RESUME, **resume_extras)
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
            on_graph_query=self._create_on_graph_query_callback(),
            on_delete_todo=self._create_on_delete_todo_callback(item_id),
            on_create_shortcut=self._create_on_create_shortcut_callback(item_id),
            **self._item_session_kwargs(item),
        )

        prompt = f"Continue working on your task:\nTask: {item['title']}\n\n{item['description']}"
        if pause_message:
            # Surface the user's note prominently — these are mid-flight course
            # corrections (e.g. "investigate a different approach"), not just
            # extra context, so we want them at the top of the resume prompt.
            prompt = (
                "The user paused you with this note — please address it before "
                "continuing:\n\n"
                f"{pause_message}\n\n"
                "---\n\n"
                + prompt
            )
        attachments = await self.db.get_attachments(item_id)
        await self.sessions.start_session_task(item_id, session, prompt, attachments, resume_id)

        return item

    async def retry_agent(self, item_id: str) -> Dict[str, Any]:
        """Retry a failed agent — resume previous session if available."""
        await self.sessions.cleanup_session(item_id)

        item = await self.items.get_or_raise(item_id)

        # Ensure worktree exists
        worktree_path = Path(item["worktree_path"]) if item.get("worktree_path") else None
        if not worktree_path or not worktree_path.exists():
            branch_name = item.get("branch_name") or f"agent/{item_id}"
            worktree_path, _, _, _ = await self.git.create_or_reuse_worktree(
                item_id, None, branch_name, repo=item.get("repo"),
            )
            await self.items.update_fields(
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

        # Track YOLO mode for retried agent
        is_yolo = config.get("bash_yolo", False)
        if is_yolo:
            self._yolo_items.add(item_id)
            await self.notifications.ws_manager.broadcast("yolo_mode_changed", {
                "item_id": item_id, "active": True,
            })
        else:
            self._yolo_items.discard(item_id)

        # Update item state
        item = await self.items.transition(item_id, Event.START)
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
            on_graph_query=self._create_on_graph_query_callback(),
            on_delete_todo=self._create_on_delete_todo_callback(item_id),
            on_create_shortcut=self._create_on_create_shortcut_callback(item_id),
            **self._item_session_kwargs(item),
        )

        prompt = f"Task: {item['title']}\n\n{item['description']}"
        attachments = await self.db.get_attachments(item_id)
        await self.sessions.start_session_task(item_id, session, prompt, attachments, resume_id)

        return item

    async def approve_item(self, item_id: str) -> Dict[str, Any]:
        """Approve a reviewed item — merge back into the base branch."""
        item = await self.items.get_or_raise(item_id)

        branch = item["branch_name"]
        base_branch = item.get("base_branch")
        worktree_path = Path(item["worktree_path"]) if item.get("worktree_path") else None
        commit_msg = item.get("commit_message")

        # Refuse to merge without an explicit base_branch. The agent's
        # worktree was forked from a specific branch (recorded as
        # base_branch at create_worktree time) and that is the ONLY correct
        # merge target. If it's missing — e.g. a legacy item, or a corrupted
        # record — we must not silently pick a fallback like "main" or "the
        # current HEAD of the target repo"; doing so was the original bug.
        if not base_branch:
            await self._log_and_notify(item_id, "system",
                "Cannot merge — item is missing base_branch (the branch this "
                "worktree was forked from). Refusing to guess a merge target. "
                "Set base_branch on the item, or recreate the worktree.")
            item = await self.items.transition(item_id, Event.MERGE_BLOCKED)
            await self.notifications.broadcast_item_updated(item)
            await self.notifications.ws_manager.broadcast("merge_blocked", {
                "item_id": item_id,
                "message": "Cannot merge — item has no recorded base branch. "
                           "The merge target is unknown.",
            })
            return item

        # Check if base repo has dirty files that overlap with the agent's changes
        from ..git.operations import run_git
        try:
            # Get locally modified tracked files (exclude untracked with no '??' prefix)
            status_output = await run_git(self.git.base_repo_path(item.get("repo")), "status", "--porcelain")
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
                    item = await self.items.transition(item_id, Event.MERGE_BLOCKED)
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

        # Check if there are any changed files — skip merge if none
        has_changes = True
        if worktree_path and branch:
            from ..git.operations import get_changed_files
            try:
                base = base_branch or "main"
                base_commit = item.get("base_commit")
                changed = await get_changed_files(
                    worktree_path, branch, base, worktree_path, base_commit
                )
                has_changes = len(changed) > 0
            except Exception as e:
                logger.warning(f"Failed to check changed files, assuming changes exist: {e}")

        if not has_changes:
            # No modified files — skip merge, just clean up and move to done
            await self._log_and_notify(item_id, "system",
                "No modified files — skipping merge")
            if worktree_path:
                await self.git.cleanup_worktree_and_branch(worktree_path, branch, repo=item.get("repo"))
            item = await self.items.transition(
                item_id, Event.REQUEST_MERGE, worktree_path=None,
            )
            # Broadcast BEFORE notify_and_auto_start_dependents — without this,
            # the frontend never sees the column change and the card stays in
            # Review until a reload. notify_and_auto_start_dependents only
            # fires a "dependencies_resolved" event, and only when dependents
            # exist, so it can't be relied on to refresh the moving card.
            await self.notifications.broadcast_item_updated(item)
            await self.notify_and_auto_start_dependents(item_id)
            return item

        success, message = await self.git.merge_agent_work(
            branch, base_branch, worktree_path, commit_msg, repo=item.get("repo"),
        )

        if success:
            self._merge_retries.pop(item_id, None)
            self._auto_approve_retries.pop(item_id, None)
            self._last_agent_message.pop(item_id, None)
            merge_sha = message  # on success, message contains the merge commit SHA
            target = base_branch or "current branch"
            short_sha = merge_sha[:8] if merge_sha else ""
            await self._log_and_notify(item_id, "system",
                f"Merged {branch} into {target} ({short_sha})")

            # Clean up worktree
            if worktree_path:
                await self.git.cleanup_worktree_and_branch(worktree_path, branch, repo=item.get("repo"))

            item = await self.items.transition(
                item_id, Event.REQUEST_MERGE,
                worktree_path=None, merge_commit=merge_sha,
            )

            # Broadcast the column change to the frontend. The
            # notify_and_auto_start_dependents call below only emits
            # "dependencies_resolved" (and only when dependents exist), so
            # without this broadcast the card stays in Review until a reload.
            # The rebase-retry success branch below already does this — keep
            # the two paths in sync.
            await self.notifications.broadcast_item_updated(item)
            await self.notify_and_auto_start_dependents(item_id)
            await self._maybe_refresh_graph_after_merge()
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

                base = base_branch or await get_current_branch(self.git.base_repo_path(item.get("repo")))
                rebase_ok, rebase_msg = await self.git.rebase_onto_base(worktree_path, base)

                if rebase_ok:
                    await self._log_and_notify(item_id, "system",
                        f"Auto-rebase onto {base} succeeded, retrying merge")

                    # Retry the merge after successful rebase
                    success2, message2 = await self.git.merge_agent_work(
                        branch, base_branch, worktree_path, commit_msg, repo=item.get("repo"),
                    )
                    if success2:
                        self._merge_retries.pop(item_id, None)
                        self._auto_approve_retries.pop(item_id, None)
                        self._last_agent_message.pop(item_id, None)
                        merge_sha = message2
                        target = base_branch or "current branch"
                        short_sha = merge_sha[:8] if merge_sha else ""
                        await self._log_and_notify(item_id, "system",
                            f"Merged {branch} into {target} ({short_sha}) after rebase")

                        if worktree_path:
                            await self.git.cleanup_worktree_and_branch(worktree_path, branch, repo=item.get("repo"))

                        item = await self.items.transition(
                            item_id, Event.REQUEST_MERGE,
                            worktree_path=None, merge_commit=merge_sha,
                        )

                        await self.notify_and_auto_start_dependents(item_id)
                        await self.notifications.broadcast_item_updated(item)
                        await self._maybe_refresh_graph_after_merge()
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
                item = await self.items.transition(item_id, Event.CONFLICT_DETECTED)
                await self.notifications.broadcast_item_updated(item)
                return item

            # Capture the agent's work as a diff before resetting
            try:
                from ..git.operations import run_git, get_current_branch
                agent_diff = await run_git(worktree_path, "diff", "HEAD~1", "HEAD")
                if not agent_diff.strip():
                    # Try diff against base
                    base = base_branch or await get_current_branch(self.git.base_repo_path(item.get("repo")))
                    agent_diff = await run_git(worktree_path, "diff", base, "HEAD")
            except Exception:
                agent_diff = ""

            if agent_diff and worktree_path:
                # Reset worktree to latest base branch
                try:
                    base = base_branch or await get_current_branch(self.git.base_repo_path(item.get("repo")))
                    # Worktrees share refs with the parent repo, so just reset
                    # directly to the base branch — no fetch needed (target project
                    # is local, not a remote clone).
                    await run_git(worktree_path, "reset", "--hard", base)
                    await self._log_and_notify(item_id, "system",
                        f"Reset worktree to latest {base}, restarting agent with previous diff "
                        f"(retry {merge_retries + 1}/{MAX_MERGE_RETRIES})")
                except Exception as e:
                    logger.warning(f"Failed to reset worktree: {e}")

                # Increment retry counter and restart agent with the diff as context
                self._merge_retries[item_id] = merge_retries + 1
                item = await self.items.transition(item_id, Event.RESOLVE_CONFLICTS)
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
            on_graph_query=self._create_on_graph_query_callback(),
                    on_delete_todo=self._create_on_delete_todo_callback(item_id),
                    **self._item_session_kwargs(item),
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
            item = await self.items.transition(item_id, Event.CONFLICT_DETECTED)

        await self.notifications.broadcast_item_updated(item)
        return item

    async def notify_and_auto_start_dependents(self, resolved_item_id: str):
        """Notify dependents that a dependency was resolved, and auto-start if configured.

        Called whenever an item enters a dependency-resolved state (column 'done'
        or 'archive') — both via the merge pipeline and via direct user moves
        (drag-and-drop into Done/Archive). Idempotent: re-running it for an
        already-processed item is a no-op for items that are already running.
        """
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
        item = await self.items.transition(item_id, Event.REQUEST_CHANGES)
        await self.notifications.broadcast_item_updated(item)

        # Start new agent session with feedback
        config = await self.db.get_agent_config()
        worktree_path = Path(item["worktree_path"])

        # Track YOLO mode
        is_yolo = config.get("bash_yolo", False)
        if is_yolo:
            self._yolo_items.add(item_id)
            await self.notifications.ws_manager.broadcast("yolo_mode_changed", {
                "item_id": item_id, "active": True,
            })
        else:
            self._yolo_items.discard(item_id)

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
            on_graph_query=self._create_on_graph_query_callback(),
            on_delete_todo=self._create_on_delete_todo_callback(item_id),
            on_create_shortcut=self._create_on_create_shortcut_callback(item_id),
            **self._item_session_kwargs(item),
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
        await self.git.cleanup_item_resources(
            item.get("worktree_path"), item.get("branch_name"), repo=item.get("repo"),
        )
        await self._log_and_notify(item_id, "user_action", "Review cancelled - work discarded")

        # Move item back to todo
        item = await self.items.transition(item_id, Event.REQUEUE, worktree_path=None)
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
            await self.git.cleanup_item_resources(
                item.get("worktree_path"), item.get("branch_name"), repo=item.get("repo"),
            )

        # Drop in-memory bookkeeping for this item.
        self._auto_approve_retries.pop(item_id, None)
        self._last_agent_message.pop(item_id, None)

        # Broadcast deletion
        await self.notifications.broadcast_item_deleted(item_id)
        return {"ok": True}

    async def shutdown(self):
        """Gracefully stop all running agents."""
        await self.sessions.cleanup_all_sessions()

    # Callback creators
    def _create_on_message_callback(self, item_id: str):
        async def on_message(text: str):
            # Track the latest assistant message so the auto-review agent can
            # cite it as the implementing agent's "final message". Each new
            # text replaces the prior one — by the time on_complete fires the
            # last one wins, which is exactly what we want.
            if text:
                self._last_agent_message[item_id] = text
            await self._log_and_notify(item_id, "agent_message", text)
        return on_message

    def _create_on_tool_use_callback(self, item_id: str):
        async def on_tool_use(name: str, inp: Dict[str, Any]):
            formatted = self.notifications.format_tool_use(name, inp)
            # Tag Bash commands with yolo_command entry type when YOLO mode is active
            if name == "Bash" and item_id in self._yolo_items:
                entry_type = "yolo_command"
                formatted = f"⚡ {formatted}"
            else:
                entry_type = "tool_use"
            await self._log_and_notify(item_id, entry_type, formatted, json.dumps(inp))
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

                # Check if the agent produced any file changes
                has_file_changes = 1  # assume yes
                current_item = await self.db.get_item(item_id)
                wt = Path(current_item["worktree_path"]) if current_item.get("worktree_path") else None
                br = current_item.get("branch_name")
                if wt and br:
                    from ..git.operations import get_changed_files
                    try:
                        base = current_item.get("base_branch") or "main"
                        base_commit = current_item.get("base_commit")
                        changed = await get_changed_files(wt, br, base, wt, base_commit)
                        has_file_changes = 1 if len(changed) > 0 else 0
                    except Exception as e:
                        logger.warning(f"Failed to check changed files for review: {e}")

                extras: Dict[str, Any] = dict(
                    session_id=result.session_id,
                    has_file_changes=has_file_changes,
                )
                if commit_message:
                    extras["commit_message"] = commit_message
                item = await self.items.transition(item_id, Event.COMPLETE, **extras)
                await self.notifications.broadcast_item_updated(item, source="agent")

                # Auto-approve workflow. Tri-state (see constants.py):
                #   OFF    — leave it for a human in the Review column.
                #   REVIEW — spin up a read-only review agent (or, with no
                #            file changes, approve directly since there's
                #            nothing to review).
                #   DIRECT — skip the review agent entirely and approve as
                #            soon as the agent finishes.
                #
                # All paths are scheduled as background tasks so we don't block
                # this callback (the review may take tens of seconds, and
                # request_changes/approve_item create new sessions that would
                # deadlock if awaited inline).
                mode = int(item.get("auto_approve") or 0)
                if mode == AUTO_APPROVE_DIRECT:
                    asyncio.create_task(self._auto_approve_direct(item_id))
                elif mode == AUTO_APPROVE_REVIEW:
                    if has_file_changes:
                        asyncio.create_task(self._run_auto_review(item_id))
                    else:
                        asyncio.create_task(self._auto_approve_no_changes(item_id))
            else:
                await self._log_and_notify(item_id, "error", f"Agent failed: {result.error}")
                item = await self.items.transition(
                    item_id, Event.FAIL, session_id=result.session_id,
                )
                await self.notifications.broadcast_item_updated(item, source="agent")
                self._add_failure_notification(item_id, result.error, result.api_error_status)

            # Remove finished session from tracking so it no longer counts as active
            self.sessions.remove_session(item_id)
            # Clean up YOLO tracking
            if item_id in self._yolo_items:
                self._yolo_items.discard(item_id)
                await self.notifications.ws_manager.broadcast("yolo_mode_changed", {
                    "item_id": item_id, "active": False,
                })

            # Process queue — a slot just opened
            await self.process_queue()

        return on_complete

    def _create_on_error_callback(self, item_id: str):
        async def on_error(error: str):
            await self._log_and_notify(item_id, "error", f"Agent error: {error}")
            item = await self.items.transition(item_id, Event.FAIL)
            await self.notifications.broadcast_item_updated(item, source="agent")
            self._add_failure_notification(item_id, error)
            # Remove finished session from tracking so it no longer counts as active
            self.sessions.remove_session(item_id)
            # Clean up YOLO tracking
            if item_id in self._yolo_items:
                self._yolo_items.discard(item_id)
                await self.notifications.ws_manager.broadcast("yolo_mode_changed", {
                    "item_id": item_id, "active": False,
                })

            # Process queue — a slot just opened
            await self.process_queue()
        return on_error

    # HTTP statuses that indicate a transient, retryable API failure rather
    # than a real task error (rate limit, overload, gateway/server hiccups).
    _TRANSIENT_API_STATUSES = frozenset({429, 500, 502, 503, 529})

    def _add_failure_notification(self, item_id: str, error: str, api_error_status: int | None = None):
        """Add a system notification for agent failures.

        When the failure carries a transient API status (429/500/529, ...),
        classify it as retryable so the user knows it isn't their task at fault.
        """
        try:
            from ..web.routes import add_notification
            short_error = (error or "")[:200]
            if api_error_status in self._TRANSIENT_API_STATUSES:
                message = (
                    f"Agent {item_id[:8]} failed: API temporarily unavailable "
                    f"(HTTP {api_error_status}). This is transient — retry the item."
                )
            else:
                message = f"Agent {item_id[:8]} failed: {short_error}"
            add_notification("error", message, source=f"agent:{item_id[:8]}")
        except Exception:
            pass

    def _create_on_clarify_callback(self, item_id: str):
        async def on_clarify(prompt: str, choices: Optional[List[str]], context: Optional[str] = None) -> str:
            # Store clarification FIRST so that any client-side auto-transition
            # triggered by the upcoming item_updated broadcast (which fetches
            # /api/items/{id}/clarification) finds the row with context.
            # Otherwise the GET races the INSERT and the question dialog can
            # open without the context until the user closes and reopens it.
            await self.db.store_clarification(item_id, prompt, choices, context)

            # Move item to questions
            item = await self.items.transition(item_id, Event.ASK)
            await self.notifications.broadcast_item_updated(item, source="agent")
            log_message = f"Agent has a question: {prompt}"
            if context:
                log_message = f"{log_message}\n\n{context}"
            await self._log_and_notify(item_id, "system", log_message)

            # Broadcast to frontend (carries context directly so listeners that
            # don't auto-transition still get the panel populated immediately).
            await self.notifications.broadcast_clarification_requested(item_id, prompt, choices, context)

            # Wait for user response
            event = asyncio.Event()
            self._clarify_events[item_id] = event
            await event.wait()

            response = self._clarify_responses.pop(item_id, "")
            self._clarify_events.pop(item_id, None)

            # Move back to doing
            item = await self.items.transition(item_id, Event.ANSWER)
            await self.notifications.broadcast_item_updated(item)
            await self._log_and_notify(item_id, "system", f"User responded: {response}")

            return response

        return on_clarify

    def _create_on_request_command_callback(self, item_id: str):
        async def on_request_command(command: str, reason: str) -> str:
            # Store as clarification FIRST so that any client-side auto-transition
            # triggered by the item_updated broadcast (which fetches
            # /api/items/{id}/clarification) finds the row immediately.
            prompt = f"__permission_request__|{command}|{reason}"
            await self.db.store_clarification(item_id, prompt, None)

            item = await self.items.transition(item_id, Event.ASK)
            await self.notifications.broadcast_item_updated(item, source="agent")
            await self._log_and_notify(
                item_id, "system",
                f"Agent requests permission to run '{command}': {reason}"
            )

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

            item = await self.items.transition(item_id, Event.ANSWER)
            await self.notifications.broadcast_item_updated(item)

            return response

        return on_request_command

    def _create_on_request_tool_callback(self, item_id: str):
        async def on_request_tool(tool_name: str, reason: str) -> str:
            # Store as clarification FIRST so that any client-side auto-transition
            # triggered by the item_updated broadcast (which fetches
            # /api/items/{id}/clarification) finds the row immediately.
            prompt = f"__tool_request__|{tool_name}|{reason}"
            await self.db.store_clarification(item_id, prompt, None)

            item = await self.items.transition(item_id, Event.ASK)
            await self.notifications.broadcast_item_updated(item, source="agent")
            await self._log_and_notify(
                item_id, "system",
                f"Agent requests permission to use '{tool_name}': {reason}"
            )

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

            item = await self.items.transition(item_id, Event.ANSWER)
            await self.notifications.broadcast_item_updated(item)

            return response

        return on_request_tool

    def _create_on_create_todo_callback(self, item_id: str):
        async def on_create_todo(title: str, description: str, epic_id: str = None, requires: list[str] = None, autostart: bool = False, auto_approve: int = 0, use_chrome: bool = False) -> Dict[str, Any]:
            # Coerce auto_approve to a known mode (0/1/2). Anything else falls back to OFF.
            try:
                auto_approve_int = int(auto_approve) if auto_approve is not None else 0
            except (TypeError, ValueError):
                auto_approve_int = 0
            if auto_approve_int not in AUTO_APPROVE_MODES:
                auto_approve_int = AUTO_APPROVE_OFF
            item = await self.db.create_todo_item(
                title, description, epic_id, autostart, auto_approve=auto_approve_int,
                use_chrome=bool(use_chrome),
            )

            # Safe default for the empty-requires footgun: a task spawned by an
            # in-flight agent must not start before the creating card's own work
            # merges, or it branches off a `main` that doesn't have that work yet.
            # When the agent asks for autostart but gives no deps, anchor the new
            # task to the creating card so it waits for our merge. Only do this
            # while the creator is still in flight (not yet merged) — if it's
            # already done/archived its work is on main and immediate start is fine.
            effective_requires = list(requires) if requires else []
            auto_anchored = False
            if autostart and not effective_requires and item["id"] != item_id:
                creator = await self.db.get_item(item_id)
                if creator and creator.get("column_name") not in ("done", "archive"):
                    effective_requires = [item_id]
                    auto_anchored = True

            if effective_requires:
                await self.db.set_item_dependencies(item["id"], effective_requires)
            await self._log_and_notify(item_id, "system", f"Created todo item: {title}")
            if auto_anchored:
                await self._log_and_notify(
                    item_id, "system",
                    f"'{title}' will wait for this card to merge before it starts "
                    "(auto-added dependency to avoid branching off an unmerged main).",
                )
            await self.notifications.broadcast_item_created(item)
            if effective_requires:
                blocked_status = await self.db.get_all_blocked_status()
                await self.notifications.ws_manager.broadcast("blocked_status_changed", {
                    "blocked": blocked_status,
                })
            if autostart and not effective_requires:
                async def _autostart_agent(new_item_id: str, new_title: str):
                    try:
                        await self.start_agent(new_item_id)
                        await self._log_and_notify(item_id, "system", f"Auto-started agent for: {new_title}")
                    except Exception as e:
                        logger.error(f"Autostart failed for item {new_item_id}: {e}")
                        await self._log_and_notify(item_id, "system", f"⚠️ Auto-start failed for '{new_title}': {e}")

                task = asyncio.create_task(_autostart_agent(item["id"], title))
                task.add_done_callback(lambda t: t.exception() if not t.cancelled() and t.exception() else None)
                item["autostart_scheduled"] = True
            return item
        return on_create_todo

    def _create_on_create_epic_callback(self, item_id: str):
        async def on_create_epic(title: str, color: str) -> Dict[str, Any]:
            epic = await self.epics.create(title, color)
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

    def _create_on_create_shortcut_callback(self, item_id: str):
        async def on_create_shortcut(name: str, command: str) -> Dict[str, Any]:
            import uuid as _uuid
            shortcuts_path = self.data_dir / "shortcuts.json" if self.data_dir else None
            if not shortcuts_path:
                return {"error": "Shortcuts not available"}

            # Load existing shortcuts
            shortcuts = []
            if shortcuts_path.exists():
                try:
                    shortcuts = json.loads(shortcuts_path.read_text())
                except Exception:
                    pass

            # Create new shortcut
            sc = {"id": _uuid.uuid4().hex[:10], "name": name, "command": command}
            shortcuts.append(sc)
            shortcuts_path.write_text(json.dumps(shortcuts, indent=2))

            await self._log_and_notify(item_id, "system", f"Created shortcut: {name} → `{command}`")
            await self.notifications.ws_manager.broadcast("shortcut_created", sc)
            return sc
        return on_create_shortcut

    def _create_on_who_am_i_callback(self, item_id: str):
        """Callback backing the who_am_i tool — returns the agent's OWN item.

        Closes over the agent's item_id so the agent can fetch its own card
        (id, title, column, dependencies) without guessing from view_board.
        """
        async def on_who_am_i() -> Dict[str, Any]:
            if not item_id:
                return {"error": "Could not determine your board item."}
            item = await self.db.get_item(item_id)
            if not item:
                return {"error": f"Board item {item_id} not found."}
            deps = await self.db.get_item_dependencies(item_id)
            return {
                "id": item["id"],
                "title": item.get("title", ""),
                "description": item.get("description", ""),
                "column_name": item.get("column_name", ""),
                "status": item.get("status"),
                "epic_id": item.get("epic_id"),
                "auto_start": item.get("auto_start"),
                "auto_approve": item.get("auto_approve"),
                "dependencies": deps or [],
            }
        return on_who_am_i

    def _create_on_view_board_callback(self):
        async def on_view_board() -> str:
            from ..config import COLUMNS
            items = await self.db.get_all_items()
            epics = await self.epics.list_all()
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

    def _create_on_graph_query_callback(self):
        async def on_graph_query(question: str) -> str:
            if not self.graph_service:
                return "Knowledge graph is not available."
            result = await self.graph_service.query(question or "")
            if result.get("ok"):
                return result.get("answer") or "(no result)"
            return f"Graph query failed: {result.get('error') or 'unknown error'}"
        return on_graph_query

    async def _maybe_refresh_graph_after_merge(self) -> None:
        """Fire-and-forget incremental graph refresh after a merge to root.

        Only when `graphify_auto_refresh` is set AND a graph already exists —
        we maintain an existing graph against mainline, but never silently build
        one the user hasn't opted into (initial build is the Settings tab). The
        refresh is free (AST) and serialized by GraphService's own build lock.
        """
        if not self.graph_service or not self.graph_service.graph_json.exists():
            return
        try:
            config = await self.db.get_agent_config()
        except Exception:
            return
        if not config.get("graphify_auto_refresh"):
            return

        async def _run():
            try:
                await self.graph_service.refresh()
            except Exception:
                logger.exception("graphify: auto-refresh after merge failed")

        asyncio.create_task(_run())

    async def _auto_approve_no_changes(self, item_id: str) -> None:
        """Auto-approve an item that completed without producing file changes.

        For these items the review card shows a "Done" button instead of
        "Approve & Merge" — there's nothing for the reviewer agent to look at,
        so we just call approve_item directly. approve_item already detects the
        no-changes case and skips the merge, transitioning the item straight to
        done.

        Scheduled as a background task from on_complete so we don't block the
        agent's completion callback.
        """
        try:
            item = await self.db.get_item(item_id)
            if not item:
                return
            # Sanity: the user (or another flow) may have already moved the
            # item out of review. In that case do nothing.
            if item.get("column_name") != "review":
                return
            if not item.get("auto_approve"):
                return
            self._auto_approve_retries.pop(item_id, None)
            await self._log_and_notify(
                item_id, "system",
                "Auto-approve: no file changes — marking done."
            )
            await self.approve_item(item_id)
        except Exception as e:
            logger.exception("Auto-approve (no-changes) failed for %s: %s", item_id, e)
            await self._log_and_notify(
                item_id, "system",
                f"Auto-approve failed to mark done: {e}. Item left for manual review."
            )

    async def _auto_approve_direct(self, item_id: str) -> None:
        """Auto-approve an item without running a review agent.

        Triggered from on_complete when the user picked the DIRECT auto-approve
        mode — i.e. "merge as soon as the agent says it's done, no second
        opinion." Calls approve_item, which handles both the no-diff and
        with-diff paths (merging when there are changes, marking done when
        there aren't).

        Scheduled as a background task from on_complete for the same reason as
        the other auto-approve paths: approve_item creates new sessions and
        would deadlock if awaited inline.
        """
        try:
            item = await self.db.get_item(item_id)
            if not item:
                return
            # Sanity: the user may have moved the item out of review before
            # this task got scheduled.
            if item.get("column_name") != "review":
                return
            mode = int(item.get("auto_approve") or 0)
            if mode != AUTO_APPROVE_DIRECT:
                return
            self._auto_approve_retries.pop(item_id, None)
            await self._log_and_notify(
                item_id, "system",
                "Auto-approve (direct): skipping review — merging now."
            )
            await self.approve_item(item_id)
        except Exception as e:
            logger.exception("Auto-approve (direct) failed for %s: %s", item_id, e)
            await self._log_and_notify(
                item_id, "system",
                f"Auto-approve (direct) failed: {e}. Item left for manual review."
            )

    async def _run_auto_review(self, item_id: str) -> None:
        """Run a one-shot auto-review agent against a just-completed item.

        Triggered from on_complete when the item has auto_approve=True. The
        review agent inspects the diff and the implementing agent's last
        message, then either:
          - APPROVES → we call approve_item to merge it and clear the counter.
          - REQUESTS CHANGES → we increment a per-item retry counter and call
            request_changes to send the comments back to the original agent.
            After _MAX_AUTO_APPROVE_RETRIES return-trips we stop auto-cycling
            and leave the item in review for a human.

        Defensive against every failure mode: if anything goes wrong we leave
        the item in review (its current state) rather than silently merging.
        """
        try:
            item = await self.db.get_item(item_id)
            if not item:
                return
            # Sanity check: the item should still be in review/auto_approve.
            # If a user cancelled or moved it during the review setup, bail.
            if item.get("column_name") != "review":
                return
            if not item.get("auto_approve"):
                return

            attempt = self._auto_approve_retries.get(item_id, 0) + 1
            if attempt > _MAX_AUTO_APPROVE_RETRIES:
                # Hit the cap. Stop the cycle and let a human step in.
                self._auto_approve_retries.pop(item_id, None)
                await self._log_and_notify(
                    item_id, "system",
                    f"Auto-approve cycle stopped after {_MAX_AUTO_APPROVE_RETRIES} "
                    f"review iterations — manual review required."
                )
                return

            self._auto_approve_retries[item_id] = attempt

            worktree_path = Path(item["worktree_path"]) if item.get("worktree_path") else None
            if not worktree_path or not worktree_path.exists():
                await self._log_and_notify(
                    item_id, "system",
                    "Auto-review skipped — worktree no longer available."
                )
                return

            # Compute the agent's full diff vs the base branch (committed +
            # uncommitted). We feed both to the reviewer so it sees the same
            # state a human reviewer would.
            from ..git.operations import run_git, get_current_branch
            base = item.get("base_branch")
            try:
                if not base:
                    base = await get_current_branch(self.git.base_repo_path(item.get("repo")))
            except Exception:
                base = "main"

            diff_parts: list[str] = []
            try:
                committed = await run_git(worktree_path, "diff", base, "HEAD")
                if committed.strip():
                    diff_parts.append(committed)
            except Exception as e:
                logger.warning(f"Auto-review: failed to read committed diff: {e}")
            try:
                # Uncommitted (working tree vs HEAD) — covers any leftover
                # work the agent didn't commit before exiting.
                uncommitted = await run_git(worktree_path, "diff", "HEAD")
                if uncommitted.strip():
                    diff_parts.append(
                        "\n# Uncommitted working-tree changes:\n" + uncommitted
                    )
            except Exception:
                pass
            full_diff = "\n".join(diff_parts).strip()

            last_message = self._last_agent_message.get(item_id, "")

            # Build Ollama env for the reviewer if the workspace is configured
            # for it. The reviewer uses the same model selection logic as the
            # implementing agent so a Claude/Ollama mix doesn't get mismatched.
            config = await self.db.get_agent_config()
            review_model = item.get("model") or config.get("model")
            ollama_env: dict[str, str] | None = None
            if config.get("ollama_enabled") and review_model and not review_model.startswith("claude-"):
                from ..constants import DEFAULT_OLLAMA_BASE_URL
                ollama_env = {
                    "ANTHROPIC_AUTH_TOKEN": "ollama",
                    "ANTHROPIC_API_KEY": "",
                    "ANTHROPIC_BASE_URL": config.get("ollama_base_url", DEFAULT_OLLAMA_BASE_URL),
                }

            await self._log_and_notify(
                item_id, "system",
                f"Auto-review starting (attempt {attempt}/{_MAX_AUTO_APPROVE_RETRIES})…"
            )

            # Mark this review-column item as actively under review so the UI
            # can render a "Reviewing" badge. Cleared in finally even if the
            # review agent crashes — never leave a stale badge.
            self._auto_reviewing.add(item_id)
            await self.notifications.ws_manager.broadcast("auto_review_changed", {
                "item_id": item_id, "active": True,
            })
            try:
                decision = await run_auto_review(
                    worktree_path=worktree_path,
                    model=review_model,
                    item_title=item.get("title", ""),
                    item_description=item.get("description", ""),
                    diff=full_diff,
                    last_message=last_message,
                    ollama_env=ollama_env,
                )
            finally:
                self._auto_reviewing.discard(item_id)
                await self.notifications.ws_manager.broadcast("auto_review_changed", {
                    "item_id": item_id, "active": False,
                })

            if decision.get("approved"):
                summary = decision.get("summary") or "Auto-review approved."
                await self._log_and_notify(
                    item_id, "system", f"Auto-review approved: {summary}"
                )
                self._auto_approve_retries.pop(item_id, None)
                try:
                    await self.approve_item(item_id)
                except Exception as e:
                    logger.exception("Auto-approve merge failed: %s", e)
                    await self._log_and_notify(
                        item_id, "system",
                        f"Auto-approve approved but merge failed: {e}"
                    )
                return

            comments = decision.get("comments") or [
                "Auto-reviewer requested changes (no specific comments)."
            ]
            await self._log_and_notify(
                item_id, "system",
                f"Auto-review requested changes (attempt {attempt}/"
                f"{_MAX_AUTO_APPROVE_RETRIES}): {'; '.join(comments)}"
            )
            try:
                await self.request_changes(item_id, comments)
            except Exception as e:
                logger.exception("Auto-approve request_changes failed: %s", e)
                await self._log_and_notify(
                    item_id, "system",
                    f"Auto-review failed to relay comments: {e}"
                )
        except Exception as e:
            logger.exception("Auto-review crashed for %s: %s", item_id, e)
            await self._log_and_notify(
                item_id, "system",
                f"Auto-review crashed: {e}. Item left for manual review."
            )

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

            item = await self.items.transition(item_id, Event.ANSWER)
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
            on_graph_query=self._create_on_graph_query_callback(),
                on_delete_todo=self._create_on_delete_todo_callback(item_id),
                **self._item_session_kwargs(item or {}),
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

    async def find_stale_worktrees(self) -> List[Dict[str, Any]]:
        """Find worktrees whose items are in a terminal state or missing from DB.

        In multi-repo mode iterates each subrepo's worktrees; in single-repo
        mode asks the one target_project for its list.
        """
        from ..git.worktree import list_worktrees

        # Collect (worktree_record, source_repo) across all repos.
        worktree_records: List[Dict[str, Any]] = []
        if self.git.is_multi():
            for repo_name in (self.git.repos or []):
                base = self.git.base_repo_path(repo_name)
                try:
                    for wt in await list_worktrees(base):
                        wt["_source_repo"] = repo_name
                        worktree_records.append(wt)
                except Exception as e:
                    logger.warning(f"Failed to list worktrees for repo {repo_name}: {e}")
        else:
            for wt in await list_worktrees(self.git.target_project):
                worktree_records.append(wt)

        stale = []
        for wt in worktree_records:
            path = wt.get("path", "")
            branch = wt.get("branch", "")
            # Only check agent worktrees (refs/heads/agent/...)
            if not branch.startswith("refs/heads/agent/"):
                continue
            branch_name = branch.removeprefix("refs/heads/")
            # Extract item_id from branch name "agent/{item_id}"
            item_id = branch_name.removeprefix("agent/")
            if not item_id:
                continue

            item = await self.db.get_item(item_id)
            if not item:
                # Item deleted from DB but worktree remains
                stale.append({"item_id": item_id, "branch_name": branch_name, "worktree_path": path, "reason": "Item no longer exists in database"})
                continue

            # Check if item is in a terminal/inactive state with no running session
            has_session = item_id in self.sessions.sessions
            try:
                state = from_columns(item.get("column_name", ""), item.get("status"))
            except UnknownStateEncoding:
                continue  # unknown legacy encoding — leave alone, audit logs it on startup

            terminal_states = {ItemState.CANCELLED, ItemState.DONE, ItemState.ARCHIVED}
            if state in terminal_states and not has_session:
                title = item.get("title", item_id[:8])
                stale.append({"item_id": item_id, "title": title, "branch_name": branch_name, "worktree_path": path, "reason": f"Item is {state.value}"})
            elif state is ItemState.BACKLOG and not has_session:
                title = item.get("title", item_id[:8])
                stale.append({"item_id": item_id, "title": title, "branch_name": branch_name, "worktree_path": path, "reason": "Item is in todo with no active agent"})

        return stale

    async def cleanup_stale_worktree(self, item_id: str) -> Dict[str, Any]:
        """Clean up a stale worktree and clear git metadata on the item."""
        item = await self.db.get_item(item_id)
        branch_name = f"agent/{item_id}"
        # Default worktree path — matches what create_or_reuse_worktree would have built
        item_repo = item.get("repo") if item else None
        worktree_path = self.git.worktree_path_for(item_id, branch_name, item_repo)

        # Use item's stored values if available
        if item:
            branch_name = item.get("branch_name") or branch_name
            worktree_path = Path(item.get("worktree_path") or str(worktree_path))

        await self.git.cleanup_item_resources(str(worktree_path), branch_name, repo=item_repo)

        # Clear git metadata on the item if it still exists
        if item:
            updated = await self.items.update_fields(
                item_id, worktree_path=None, branch_name=None, base_branch=None, base_commit=None
            )
            await self.notifications.broadcast_item_updated(updated)

        return {"ok": True, "item_id": item_id}

    async def _validate_ollama_model(self, item_id: str, model: str, config: Dict[str, Any]) -> str:
        """Check if an Ollama model is available. Falls back to config default if not."""
        import urllib.request
        import urllib.error
        from ..constants import DEFAULT_OLLAMA_BASE_URL
        base_url = config.get("ollama_base_url", DEFAULT_OLLAMA_BASE_URL)
        try:
            req = urllib.request.Request(f"{base_url}/api/tags", method="GET")
            req.add_header("Accept", "application/json")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode())
            available = {m["name"] for m in data.get("models", [])}
            if model in available:
                return model
            # Model not found — fall back
            from ..constants import DEFAULT_MODEL
            fallback = config.get("model") or DEFAULT_MODEL
            await self._log_and_notify(
                item_id, "system",
                f"Ollama model '{model}' not available (pulled models: {', '.join(sorted(available)) or 'none'}). "
                f"Falling back to {fallback}."
            )
            return fallback
        except Exception:
            # Can't reach Ollama — let it proceed and fail with a clear error
            return model

    async def _log_and_notify(self, item_id: str, entry_type: str, content: str, metadata: Optional[str] = None):
        """Log entry to database and broadcast notification."""
        await self.db.log_entry(item_id, entry_type, content, metadata)
        await self.notifications.broadcast_agent_log(item_id, entry_type, content)