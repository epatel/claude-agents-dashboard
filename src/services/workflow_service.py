"""Workflow service for coordinating agent workflows and state transitions."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..agent.profiles import is_kimi_model, is_ollama_model, resolve_local_env
from ..agent.review_agent import run_auto_review
from ..config import epic_plan_relpath
from ..constants import AUTO_APPROVE_DIRECT
from ..domain.item_state import Event
from ..repositories.epic_repository import EpicRepository
from ..repositories.item_repository import ItemRepository
from .database_service import DatabaseService
from .git_service import GitService
from .notification_service import NotificationService
from .session_service import SessionService
from .workflow_board_tools import BoardToolCallbacksMixin
from .workflow_callbacks import AgentCallbacksMixin
from .workflow_helpers import _worktree_of
from .workflow_peek import WorktreePeekMixin
from .workflow_worktrees import StaleWorktreeMixin

logger = logging.getLogger(__name__)

# Hard cap on auto-review return-trips before falling back to manual review.
_MAX_AUTO_APPROVE_RETRIES = 3


def _short_file_list(paths: set, limit: int = 5) -> str:
    """Sorted, comma-separated paths, capped at ``limit`` with a '(+N more)' tail."""
    file_list = ", ".join(sorted(paths)[:limit])
    if len(paths) > limit:
        file_list += f" (+{len(paths) - limit} more)"
    return file_list


class WorkflowService(AgentCallbacksMixin, BoardToolCallbacksMixin, WorktreePeekMixin, StaleWorktreeMixin):
    """Coordinates workflows and state transitions between services.

    Agent-session callbacks, board-tool callbacks, the worktree peek and
    stale-worktree cleanup live in the mixins (``workflow_callbacks`` /
    ``workflow_board_tools`` / ``workflow_peek`` / ``workflow_worktrees``); this
    module keeps the lifecycle, queue, merge and auto-approve flows.
    """

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

    async def _item_session_kwargs(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Per-item extra kwargs for SessionService.create_session.

        Always carries the item's `use_chrome` flag; adds multi-repo read-scope
        kwargs when in multi-repo mode, plus the epic's shared-plan path when the
        item belongs to an epic. Callers splat it: `**(await ...)`.
        Uses getattr so mocks that don't expose `repos` (e.g. MagicMock spec'd
        against GitService before this attribute existed) behave as single-mode.
        """
        item = item or {}
        kwargs: Dict[str, Any] = {
            "use_chrome": bool(item.get("use_chrome")),
            # Self-view tool: lets the agent fetch its own card (incl. its item ID
            # for `requires`) instead of guessing from view_board. Threaded here so
            # it reaches every create_session call site in one place.
            "on_who_am_i": self._create_on_who_am_i_callback(item.get("id")),
            # Peek tool: lets this agent read what the other running agents have
            # changed in their worktrees, so parallel work converges instead of
            # colliding at merge time.
            "on_peek_worktree": self._create_on_peek_worktree_callback(item.get("id")),
        }
        kwargs.update(await self._epic_plan_kwargs(item.get("epic_id")))
        kwargs.update(self._multi_repo_kwargs(item.get("repo")))
        return kwargs

    async def _epic_plan_kwargs(self, epic_id: Optional[str]) -> Dict[str, Any]:
        """Epic-scoped shared plan: tasks are usually created under an epic, so
        point the agent at that epic's plan file (derived from the epic title)
        in addition to the repo-root project-plan.md."""
        if not epic_id:
            return {}
        epic = await self.epics.get(epic_id)
        return {"epic_plan_relpath": epic_plan_relpath(epic["title"])} if epic else {}

    def _multi_repo_kwargs(self, item_repo: Optional[str]) -> Dict[str, Any]:
        """Multi-repo read scope: every known repo except the one the item is
        actively working on (the agent's own repo is reached via the worktree,
        not as a sibling). Empty in single-repo mode."""
        repos = getattr(self.git, "repos", None)
        if not repos:
            return {}
        return {
            "workspace_root": self.git.target_project,
            "sibling_repo_paths": [self.git.base_repo_path(r) for r in repos if r != item_repo],
            "item_repo_name": item_repo,
        }

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
        await self._track_yolo(item_id, config, announce=True)

        # Validate Ollama model availability before creating the session
        model = item.get("model") or config.get("model")
        if is_ollama_model(model) and config.get("ollama_enabled"):
            model = await self._validate_ollama_model(item_id, model, config)

        prompt = f"Task: {item['title']}\n\n{item['description']}"
        attachments = await self.db.get_attachments(item_id)
        if attachments:
            await self._log_and_notify(item_id, "system", f"Found {len(attachments)} image attachment(s) for agent")

        await self._launch_session(item, config, prompt, model=model, attachments=attachments)
        return item

    def _session_callbacks(self, item_id: str) -> Dict[str, Any]:
        """The per-item callbacks every agent session is created with."""
        return dict(
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
        )

    async def _launch_session(
        self,
        item: Dict[str, Any],
        config: Dict[str, Any],
        prompt: str,
        *,
        model: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        resume_id: Optional[str] = None,
    ) -> None:
        """Create the agent session for ``item`` and start it in the background.

        Every start/resume/retry/restart path goes through here so all sessions
        get the same callbacks and per-item kwargs. ``model`` defaults to the
        item's model, then the config model.
        """
        item_id = item["id"]
        session = await self.sessions.create_session(
            item_id, Path(item["worktree_path"]), config,
            model or item.get("model") or config.get("model"),
            **self._session_callbacks(item_id),
            **(await self._item_session_kwargs(item)),
        )
        await self.sessions.start_session_task(item_id, session, prompt, attachments, resume_id)

    async def _track_yolo(self, item_id: str, config: Dict[str, Any], *, announce: bool = False) -> None:
        """Record whether this item's session runs in YOLO (bash_yolo) mode."""
        if not config.get("bash_yolo", False):
            self._yolo_items.discard(item_id)
            return
        self._yolo_items.add(item_id)
        if announce:
            await self._log_and_notify(item_id, "yolo_command",
                "⚠️ **YOLO mode active** — all bash commands bypass permission checks")
        await self.notifications.ws_manager.broadcast("yolo_mode_changed", {
            "item_id": item_id, "active": True,
        })

    async def _untrack_yolo(self, item_id: str) -> None:
        """Clear YOLO tracking for an item whose session has ended."""
        if item_id in self._yolo_items:
            self._yolo_items.discard(item_id)
            await self.notifications.ws_manager.broadcast("yolo_mode_changed", {
                "item_id": item_id, "active": False,
            })

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
        await self._untrack_yolo(item_id)

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
        await self._track_yolo(item_id, config)

        # Clear pause_message on the same write that performs the transition
        # so the note is consumed exactly once.
        resume_extras: Dict[str, Any] = {}
        if pause_message or item.get("pause_message"):
            resume_extras["pause_message"] = None
        item = await self.items.transition(item_id, Event.RESUME, **resume_extras)
        await self.notifications.broadcast_item_updated(item)

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
        await self._launch_session(item, config, prompt, attachments=attachments, resume_id=resume_id)
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
        config = await self.db.get_agent_config()
        await self._track_yolo(item_id, config)

        item = await self.items.transition(item_id, Event.START)
        await self.notifications.broadcast_item_updated(item)

        prompt = f"Task: {item['title']}\n\n{item['description']}"
        attachments = await self.db.get_attachments(item_id)
        await self._launch_session(item, config, prompt, attachments=attachments, resume_id=resume_id)
        return item

    # How many times a merge conflict may restart the agent with its previous
    # diff before the item is left in the conflict state for a human.
    _MAX_MERGE_RETRIES = 2

    async def approve_item(self, item_id: str) -> Dict[str, Any]:
        """Approve a reviewed item — merge back into the base branch.

        Phases: refuse without a recorded base branch → refuse when the base
        repo has uncommitted changes to the same files → mark done without a
        merge when there are no changes → merge → on failure, auto-rebase and
        retry → on failure again, restart the agent with its previous diff.
        """
        item = await self.items.get_or_raise(item_id)

        # Refuse to merge without an explicit base_branch. The agent's
        # worktree was forked from a specific branch (recorded as
        # base_branch at create_worktree time) and that is the ONLY correct
        # merge target. If it's missing — e.g. a legacy item, or a corrupted
        # record — we must not silently pick a fallback like "main" or "the
        # current HEAD of the target repo"; doing so was the original bug.
        if not item.get("base_branch"):
            return await self._block_merge(
                item_id,
                "Cannot merge — item is missing base_branch (the branch this "
                "worktree was forked from). Refusing to guess a merge target. "
                "Set base_branch on the item, or recreate the worktree.",
                "Cannot merge — item has no recorded base branch. "
                "The merge target is unknown.",
            )

        overlap = await self._dirty_overlap(item)
        if overlap:
            file_list = _short_file_list(overlap)
            return await self._block_merge(
                item_id,
                f"Cannot merge — conflicting uncommitted changes in: {file_list}",
                f"Cannot merge because these files have uncommitted changes "
                f"in the target repo: {file_list}. "
                f"Please commit or stash your changes, then try again.",
            )

        if not await self._has_changes_to_merge(item):
            return await self._finish_without_merge(item)

        success, message = await self.git.merge_agent_work(
            item["branch_name"], item["base_branch"], _worktree_of(item),
            item.get("commit_message"), repo=item.get("repo"),
        )
        if success:
            return await self._finish_merge(item, merge_sha=message)

        await self._log_and_notify(item_id, "system",
            f"Merge failed — {message[:200]}. Attempting auto-rebase...")
        if _worktree_of(item):
            merged = await self._rebase_and_retry_merge(item)
            if merged:
                return merged
        return await self._restart_for_conflicts(item)

    async def _block_merge(self, item_id: str, log_message: str, ui_message: str) -> Dict[str, Any]:
        """Move the item to merge_blocked and tell the user why."""
        await self._log_and_notify(item_id, "system", log_message)
        item = await self.items.transition(item_id, Event.MERGE_BLOCKED)
        await self.notifications.broadcast_item_updated(item)
        await self.notifications.ws_manager.broadcast("merge_blocked", {
            "item_id": item_id, "message": ui_message,
        })
        return item

    async def _dirty_overlap(self, item: Dict[str, Any]) -> set:
        """Files with uncommitted changes in the base repo that the agent also changed.

        Fails open: if git can't be read, no overlap is reported.
        """
        worktree_path = _worktree_of(item)
        try:
            dirty_files = await self._dirty_base_files(item.get("repo"))
            if not (dirty_files and worktree_path):
                return set()
            return dirty_files & await self._agent_changed_files(worktree_path, item["base_branch"])
        except Exception as e:
            logger.warning(f"Failed to check repo status: {e}")
            return set()

    async def _dirty_base_files(self, repo: Optional[str]) -> set:
        """Tracked files with uncommitted changes in the base repo (untracked ignored)."""
        from ..git.operations import run_git
        status_output = await run_git(self.git.base_repo_path(repo), "status", "--porcelain")
        dirty_files = set()
        for line in status_output.strip().splitlines():
            if not line or line.startswith("??"):
                continue  # skip untracked files
            # porcelain format: XY<space>filename (XY = 2 status chars);
            # renames read "old -> new" and we want the new name.
            filepath = line[2:].lstrip(" ").split(" -> ")[-1].strip()
            if filepath:
                dirty_files.add(filepath)
        return dirty_files

    async def _agent_changed_files(self, worktree_path: Path, base: str) -> set:
        """Files the agent changed: committed vs base, plus unstaged and staged."""
        from ..git.operations import run_git

        def names(output: str) -> set:
            return {f.strip() for f in output.strip().splitlines() if f.strip()}

        agent_files = set()
        try:
            agent_files |= names(await run_git(worktree_path, "diff", "--name-only", base, "HEAD"))
        except Exception:
            pass
        try:
            agent_files |= names(await run_git(worktree_path, "diff", "--name-only"))
            agent_files |= names(await run_git(worktree_path, "diff", "--name-only", "--cached"))
        except Exception as e:
            logger.warning(f"Failed to get worktree uncommitted files: {e}")
        return agent_files

    async def _has_changes_to_merge(self, item: Dict[str, Any]) -> bool:
        """Whether the agent's branch changed any files. Assumes yes when unsure."""
        worktree_path, branch = _worktree_of(item), item.get("branch_name")
        if not (worktree_path and branch):
            return True
        from ..git.operations import get_changed_files
        try:
            changed = await get_changed_files(
                worktree_path, branch, item["base_branch"], worktree_path, item.get("base_commit")
            )
            return len(changed) > 0
        except Exception as e:
            logger.warning(f"Failed to check changed files, assuming changes exist: {e}")
            return True

    async def _finish_without_merge(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """No modified files — skip the merge, clean up and move to done."""
        item_id, worktree_path = item["id"], _worktree_of(item)
        await self._log_and_notify(item_id, "system", "No modified files — skipping merge")
        if worktree_path:
            await self.git.cleanup_worktree_and_branch(worktree_path, item["branch_name"], repo=item.get("repo"))
        item = await self.items.transition(item_id, Event.REQUEST_MERGE, worktree_path=None)
        # Broadcast BEFORE notify_and_auto_start_dependents — that only fires
        # "dependencies_resolved" (and only when dependents exist), so without
        # this the card stays in Review until a reload.
        await self.notifications.broadcast_item_updated(item)
        await self.notify_and_auto_start_dependents(item_id)
        return item

    async def _finish_merge(self, item: Dict[str, Any], merge_sha: str, note: str = "") -> Dict[str, Any]:
        """Record a successful merge: clean up, move to done, unblock dependents."""
        item_id, branch, worktree_path = item["id"], item["branch_name"], _worktree_of(item)
        self._merge_retries.pop(item_id, None)
        self._auto_approve_retries.pop(item_id, None)
        self._last_agent_message.pop(item_id, None)
        short_sha = merge_sha[:8] if merge_sha else ""
        await self._log_and_notify(item_id, "system",
            f"Merged {branch} into {item['base_branch']} ({short_sha}){note}")

        if worktree_path:
            await self.git.cleanup_worktree_and_branch(worktree_path, branch, repo=item.get("repo"))
        item = await self.items.transition(
            item_id, Event.REQUEST_MERGE, worktree_path=None, merge_commit=merge_sha,
        )
        # Broadcast the column change BEFORE notify_and_auto_start_dependents,
        # for the same reason as in _finish_without_merge.
        await self.notifications.broadcast_item_updated(item)
        await self.notify_and_auto_start_dependents(item_id)
        await self._maybe_refresh_graph_after_merge()
        return item

    async def _rebase_and_retry_merge(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Rebase the worktree onto its base and merge again. The done item, or None."""
        from ..git.operations import commit_worktree_changes
        item_id, branch, base = item["id"], item["branch_name"], item["base_branch"]
        worktree_path, commit_msg = _worktree_of(item), item.get("commit_message")

        # Commit any uncommitted work first
        try:
            await commit_worktree_changes(worktree_path, commit_msg or f"Agent work on {branch}")
        except Exception:
            pass

        rebase_ok, rebase_msg = await self.git.rebase_onto_base(worktree_path, base)
        if not rebase_ok:
            await self._log_and_notify(item_id, "system",
                f"Auto-rebase failed ({rebase_msg[:100]}), falling back to agent restart")
            return None

        await self._log_and_notify(item_id, "system",
            f"Auto-rebase onto {base} succeeded, retrying merge")
        success, message = await self.git.merge_agent_work(
            branch, base, worktree_path, commit_msg, repo=item.get("repo"),
        )
        if success:
            return await self._finish_merge(item, merge_sha=message, note=" after rebase")
        await self._log_and_notify(item_id, "system",
            f"Merge still failed after rebase: {message[:200]}")
        return None

    async def _restart_for_conflicts(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Restart the agent on the updated base with its previous diff as context.

        Gives up (conflict state) after _MAX_MERGE_RETRIES restarts, or when no
        diff of the agent's work can be captured.
        """
        item_id, base, worktree_path = item["id"], item["base_branch"], _worktree_of(item)
        merge_retries = self._merge_retries.get(item_id, 0)
        if merge_retries >= self._MAX_MERGE_RETRIES:
            await self._log_and_notify(item_id, "system",
                f"Conflict resolution failed after {merge_retries} retries. Manual intervention needed.")
            return await self._mark_conflict(item_id)

        agent_diff = await self._capture_agent_diff(worktree_path, base)
        if not (agent_diff and worktree_path):
            return await self._mark_conflict(item_id)

        from ..git.operations import run_git
        try:
            # Worktrees share refs with the parent repo, so reset straight to
            # the base branch — no fetch needed (the target project is local).
            await run_git(worktree_path, "reset", "--hard", base)
            await self._log_and_notify(item_id, "system",
                f"Reset worktree to latest {base}, restarting agent with previous diff "
                f"(retry {merge_retries + 1}/{self._MAX_MERGE_RETRIES})")
        except Exception as e:
            logger.warning(f"Failed to reset worktree: {e}")

        self._merge_retries[item_id] = merge_retries + 1
        item = await self.items.transition(item_id, Event.RESOLVE_CONFLICTS)
        await self.notifications.broadcast_item_updated(item)

        config = await self.db.get_agent_config()
        conflict_prompt = (
            f"Your previous changes caused a merge conflict. The base branch has been updated.\n\n"
            f"Here is the diff of your previous work — please reapply these changes to the "
            f"updated codebase, resolving any conflicts:\n\n```diff\n{agent_diff}\n```\n\n"
            f"Original task: {item['title']}\n\n{item['description']}"
        )
        await self._launch_session(item, config, conflict_prompt)
        return item

    async def _capture_agent_diff(self, worktree_path: Optional[Path], base: str) -> str:
        """The agent's work as a diff (last commit, else vs base); '' if unavailable."""
        from ..git.operations import run_git
        try:
            agent_diff = await run_git(worktree_path, "diff", "HEAD~1", "HEAD")
            if not agent_diff.strip():
                agent_diff = await run_git(worktree_path, "diff", base, "HEAD")
            return agent_diff
        except Exception:
            return ""

    async def _mark_conflict(self, item_id: str) -> Dict[str, Any]:
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

        # Resume the conversation with the feedback in a new session
        config = await self.db.get_agent_config()
        await self._track_yolo(item_id, config)
        attachments = await self.db.get_attachments(item_id)
        await self._launch_session(
            item, config, feedback, attachments=attachments, resume_id=item.get("session_id"),
        )
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
        await self._approve_without_review(
            item_id,
            required_mode=None,
            start_message="Auto-approve: no file changes — marking done.",
            log_tag="no-changes",
            failure_prefix="Auto-approve failed to mark done",
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
        await self._approve_without_review(
            item_id,
            required_mode=AUTO_APPROVE_DIRECT,
            start_message="Auto-approve (direct): skipping review — merging now.",
            log_tag="direct",
            failure_prefix="Auto-approve (direct) failed",
        )

    async def _auto_approvable_item(
        self, item_id: str, required_mode: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """The item if it is still in Review with auto-approve on, else None.

        The user (or another flow) may have moved the item out of review, or
        turned auto-approve off, before a background auto-approve task ran.
        ``required_mode`` additionally pins the exact auto-approve mode.
        """
        item = await self.db.get_item(item_id)
        if not item or item.get("column_name") != "review":
            return None
        mode = int(item.get("auto_approve") or 0)
        if not mode:
            return None
        if required_mode is not None and mode != required_mode:
            return None
        return item

    async def _approve_without_review(
        self, item_id: str, *, required_mode: Optional[int], start_message: str,
        log_tag: str, failure_prefix: str,
    ) -> None:
        """Approve an auto-approve item straight away, with no review agent."""
        try:
            if not await self._auto_approvable_item(item_id, required_mode):
                return
            self._auto_approve_retries.pop(item_id, None)
            await self._log_and_notify(item_id, "system", start_message)
            await self.approve_item(item_id)
        except Exception as e:
            logger.exception("Auto-approve (%s) failed for %s: %s", log_tag, item_id, e)
            await self._log_and_notify(
                item_id, "system",
                f"{failure_prefix}: {e}. Item left for manual review."
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
            item = await self._auto_approvable_item(item_id)
            if not item:
                return
            attempt = await self._next_auto_review_attempt(item_id)
            if attempt is None:
                return

            worktree_path = _worktree_of(item)
            if not worktree_path or not worktree_path.exists():
                await self._log_and_notify(
                    item_id, "system",
                    "Auto-review skipped — worktree no longer available."
                )
                return

            # The agent's full diff vs the base branch (committed + uncommitted),
            # so the reviewer sees the same state a human reviewer would.
            full_diff = await self._full_agent_diff(worktree_path, await self._review_base_branch(item))
            last_message = self._last_agent_message.get(item_id, "")

            model_env = await self._review_model_and_env(item_id, item)
            if model_env is None:
                return
            review_model, local_env = model_env

            await self._log_and_notify(
                item_id, "system",
                f"Auto-review starting (attempt {attempt}/{_MAX_AUTO_APPROVE_RETRIES})…"
            )
            decision = await self._review_with_badge(item_id, dict(
                worktree_path=worktree_path,
                model=review_model,
                item_title=item.get("title", ""),
                item_description=item.get("description", ""),
                diff=full_diff,
                last_message=last_message,
                local_env=local_env,
            ))
            await self._apply_review_decision(item_id, decision, attempt)
        except Exception as e:
            logger.exception("Auto-review crashed for %s: %s", item_id, e)
            await self._log_and_notify(
                item_id, "system",
                f"Auto-review crashed: {e}. Item left for manual review."
            )

    async def _next_auto_review_attempt(self, item_id: str) -> Optional[int]:
        """Count one more review cycle; None (after logging) once the cap is hit."""
        attempt = self._auto_approve_retries.get(item_id, 0) + 1
        if attempt > _MAX_AUTO_APPROVE_RETRIES:
            # Hit the cap. Stop the cycle and let a human step in.
            self._auto_approve_retries.pop(item_id, None)
            await self._log_and_notify(
                item_id, "system",
                f"Auto-approve cycle stopped after {_MAX_AUTO_APPROVE_RETRIES} "
                f"review iterations — manual review required."
            )
            return None
        self._auto_approve_retries[item_id] = attempt
        return attempt

    async def _review_base_branch(self, item: Dict[str, Any]) -> str:
        """The item's base branch, else the base repo's current branch, else "main"."""
        from ..git.operations import get_current_branch
        base = item.get("base_branch")
        try:
            if not base:
                base = await get_current_branch(self.git.base_repo_path(item.get("repo")))
        except Exception:
            base = "main"
        return base

    @staticmethod
    async def _full_agent_diff(worktree_path: Path, base: str) -> str:
        """Committed diff vs ``base`` plus any uncommitted working-tree changes."""
        from ..git.operations import run_git
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
        return "\n".join(diff_parts).strip()

    async def _review_model_and_env(self, item_id: str, item: Dict[str, Any]) -> Optional[tuple]:
        """(model, local-provider env) for the reviewer; None (after logging) for Kimi.

        The reviewer uses the same model selection logic as the implementing
        agent so a Claude/local mix doesn't get mismatched.
        """
        config = await self.db.get_agent_config()
        review_model = item.get("model") or config.get("model")
        # The one-shot reviewer runs on the Claude Agent SDK; Kimi models
        # (separate runtime, experimental) are not supported there yet.
        # Leave the item in Review for a human rather than mis-routing.
        if is_kimi_model(review_model):
            await self._log_and_notify(
                item_id, "system",
                "Auto-review is not yet supported for Kimi models — "
                "leaving item in Review for manual approval."
            )
            return None
        return review_model, resolve_local_env(config, review_model)

    async def _review_with_badge(self, item_id: str, review_kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Run the review agent while the UI shows a "Reviewing" badge on the item.

        The badge is cleared in finally even if the review agent crashes —
        never leave a stale badge.
        """
        self._auto_reviewing.add(item_id)
        await self.notifications.ws_manager.broadcast("auto_review_changed", {
            "item_id": item_id, "active": True,
        })
        try:
            return await run_auto_review(**review_kwargs)
        finally:
            self._auto_reviewing.discard(item_id)
            await self.notifications.ws_manager.broadcast("auto_review_changed", {
                "item_id": item_id, "active": False,
            })

    async def _apply_review_decision(self, item_id: str, decision: Dict[str, Any], attempt: int) -> None:
        """Merge on approval; otherwise send the reviewer's comments back to the agent."""
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
            # Include original task so agent knows what to do even without resume
            restart_prompt = (
                f"Permission for '{command}' was granted. "
                f"You can now run {command} commands.\n\n"
                f"Continue with your original task:\n"
                f"Task: {item.get('title', '')}\n\n{item.get('description', '')}"
            )
            await self._launch_session(item, config, restart_prompt, resume_id=resume_id)
        except Exception as e:
            logger.error(f"Failed to restart session for {item_id}: {e}")
            await self._log_and_notify(
                item_id, "system", f"Failed to restart session: {e}"
            )

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