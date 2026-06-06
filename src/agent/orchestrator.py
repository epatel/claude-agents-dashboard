"""Refactored orchestrator using focused services."""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..database import Database
from ..repositories.epic_repository import EpicRepository
from ..repositories.item_repository import ItemRepository
from ..web.websocket import ConnectionManager
from ..services import (
    DatabaseService,
    GitService,
    GraphService,
    NotificationService,
    SessionService,
    WorkflowService,
)

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    """Manages running agent instances, delegating to focused services."""

    def __init__(
        self,
        target_project: Path,
        data_dir: Path,
        db: Database,
        ws_manager: ConnectionManager,
        repos: list[str] | None = None,
    ):
        self.target_project = target_project
        self.data_dir = data_dir
        self.worktree_dir = data_dir / "worktrees"
        self.worktree_dir.mkdir(exist_ok=True)
        # None = single-repo mode (target_project IS the repo).
        # list[str] = multi-repo mode (target_project is the parent; repos are subdir names).
        self.repos = repos

        # Initialize services
        self.db_service = DatabaseService(db)
        self.item_repository = ItemRepository(self.db_service)
        self.epic_repository = EpicRepository(self.db_service)
        self.git_service = GitService(target_project, self.worktree_dir, repos=repos)
        self.notification_service = NotificationService(ws_manager)
        self.graph_service = GraphService(
            target_project, self.notification_service, repos=repos
        )
        self.session_service = SessionService()
        self.workflow_service = WorkflowService(
            self.db_service,
            self.git_service,
            self.notification_service,
            self.session_service,
            data_dir=data_dir,
            item_repository=self.item_repository,
            epic_repository=self.epic_repository,
        )

        # Keep references for backward compatibility
        self.db = db
        self.ws_manager = ws_manager

    async def start_agent(self, item_id: str) -> Dict[str, Any]:
        """Start an agent for an item. Creates worktree, launches agent."""
        return await self.workflow_service.start_agent(item_id)

    async def start_copy_agent(self, item_id: str) -> Dict[str, Any]:
        """Copy a todo item and start the copy, leaving the original in todo."""
        return await self.workflow_service.start_copy_agent(item_id)

    async def cancel_agent(self, item_id: str) -> Dict[str, Any]:
        """Cancel a running agent."""
        return await self.workflow_service.cancel_agent(item_id)

    async def pause_agent(
        self, item_id: str, message: Optional[str] = None
    ) -> Dict[str, Any]:
        """Pause a running agent — save session for later resumption.

        ``message`` is an optional note for the agent (e.g. "investigate a
        different approach") that will be prepended to the resume prompt.
        """
        return await self.workflow_service.pause_agent(item_id, message)

    async def resume_agent(
        self, item_id: str, message: Optional[str] = None
    ) -> Dict[str, Any]:
        """Resume a paused agent.

        ``message`` is an optional fresh note from the user (e.g. submitted via
        the work-log "Continue" form) that takes precedence over any
        ``pause_message`` stored when the agent was paused.
        """
        return await self.workflow_service.resume_agent(item_id, message)

    async def retry_agent(self, item_id: str) -> Dict[str, Any]:
        """Retry a failed agent — restart from scratch in existing worktree."""
        return await self.workflow_service.retry_agent(item_id)

    async def approve_item(self, item_id: str) -> Dict[str, Any]:
        """Approve a reviewed item — merge back into the base branch."""
        return await self.workflow_service.approve_item(item_id)

    async def request_changes(self, item_id: str, comments: List[str]) -> Dict[str, Any]:
        """Send review comments back to the agent."""
        return await self.workflow_service.request_changes(item_id, comments)

    async def cancel_review(self, item_id: str) -> Dict[str, Any]:
        """Cancel a review - discard changes and move item back to todo."""
        return await self.workflow_service.cancel_review(item_id)

    async def submit_clarification(self, item_id: str, response: str) -> Dict[str, Any]:
        """Submit a question response to a waiting agent."""
        return await self.workflow_service.submit_clarification(item_id, response)

    async def delete_item(self, item_id: str) -> Dict[str, Any]:
        """Delete an item and clean up all associated resources."""
        return await self.workflow_service.delete_item(item_id)

    async def shutdown(self):
        """Gracefully stop all running agents."""
        await self.workflow_service.shutdown()

    # Legacy compatibility methods - delegate to services
    async def _update_item(self, item_id: str, **kwargs):
        """Legacy direct-update path retained for integration tests that
        bypass the SM to seed item state. Routes through the repo so the
        column allowlist is still enforced. Tests that use this should
        gradually migrate to item_repository.transition / update_fields."""
        if "column_name" in kwargs or "status" in kwargs:
            # Direct state writes used by integration test setup. Bypass
            # the SM here on purpose — the test seeds an arbitrary state.
            item = await self.db_service.update_item(item_id, **kwargs)
        else:
            item = await self.item_repository.update_fields(item_id, **kwargs)
        await self.notification_service.broadcast_item_updated(item)
        return item

    async def _log(self, item_id: str, entry_type: str, content: str, metadata: str | None = None):
        """Legacy method for backward compatibility."""
        await self.db_service.log_entry(item_id, entry_type, content, metadata)
        await self.notification_service.broadcast_agent_log(item_id, entry_type, content)

    def _format_tool_use(self, name: str, inp: Dict[str, Any]) -> str:
        """Legacy method for backward compatibility."""
        return self.notification_service.format_tool_use(name, inp)

    async def _get_agent_config(self) -> Dict[str, Any]:
        """Legacy method for backward compatibility."""
        return await self.db_service.get_agent_config()

    # Properties for backward compatibility
    @property
    def sessions(self):
        """Legacy property for accessing sessions."""
        return self.session_service.sessions