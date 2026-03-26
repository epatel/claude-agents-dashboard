"""Session service for managing agent session lifecycle."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..agent.session import AgentSession

logger = logging.getLogger(__name__)


class SessionService:
    """Manages agent sessions and their lifecycle."""

    def __init__(self):
        self.sessions: Dict[str, AgentSession] = {}
        self._agent_tasks: Dict[str, asyncio.Task] = {}  # item_id -> _run_agent task
        self._last_agent_messages: Dict[str, str] = {}  # item_id -> last agent text
        self._commit_messages: Dict[str, str] = {}  # item_id -> commit message from tool

    async def create_session(self, item_id: str, worktree_path: Path, config: Dict[str, Any],
                           model: Optional[str] = None,
                           on_message: Optional[Callable] = None,
                           on_tool_use: Optional[Callable] = None,
                           on_thinking: Optional[Callable] = None,
                           on_complete: Optional[Callable] = None,
                           on_error: Optional[Callable] = None,
                           on_clarify: Optional[Callable] = None,
                           on_create_todo: Optional[Callable] = None,
                           on_set_commit_message: Optional[Callable] = None,
                           on_request_command: Optional[Callable] = None) -> AgentSession:
        """Create a new agent session with all callbacks."""
        # Use provided model or fall back to config model
        session_model = model or config.get("model")

        # Build system prompt with project context
        system_prompt = config.get("system_prompt", "") or ""
        project_context = config.get("project_context", "") or ""
        if project_context:
            system_prompt = f"{system_prompt}\n\nProject context:\n{project_context}"

        # Create default message callback if none provided
        if not on_message:
            async def default_on_message(text: str, iid: str = item_id):
                self._last_agent_messages[iid] = text

            on_message = default_on_message

        # Parse plugins from config
        plugins = self._parse_plugins(config.get("plugins"))

        # Parse allowed commands from config
        allowed_commands_raw = config.get("allowed_commands", "[]")
        try:
            allowed_commands = json.loads(allowed_commands_raw) if isinstance(allowed_commands_raw, str) else (allowed_commands_raw or [])
        except (json.JSONDecodeError, TypeError):
            allowed_commands = []

        session = AgentSession(
            worktree_path=worktree_path,
            system_prompt=system_prompt,
            model=session_model,
            on_message=on_message,
            on_tool_use=on_tool_use,
            on_thinking=on_thinking,
            on_complete=on_complete,
            on_error=on_error,
            on_clarify=on_clarify,
            on_create_todo=on_create_todo,
            on_set_commit_message=on_set_commit_message,
            on_request_command=on_request_command,
            mcp_servers=config.get("mcp_servers"),
            mcp_enabled=config.get("mcp_enabled", False),
            plugins=plugins,
            allowed_commands=allowed_commands,
            bash_yolo=config.get("bash_yolo", False),
        )

        self.sessions[item_id] = session
        return session

    async def start_session_task(self, item_id: str, session: AgentSession, prompt: str,
                                attachments: Optional[List[Dict[str, Any]]] = None,
                                resume_session_id: Optional[str] = None):
        """Start an agent session as a background task."""
        async def run_agent():
            try:
                await session.start(prompt, attachments=attachments, resume_session_id=resume_session_id)
            except Exception as e:
                logger.exception(f"Agent failed to start for {item_id}")
                if session.on_error:
                    await session.on_error(str(e))

        task = asyncio.create_task(run_agent())
        self._agent_tasks[item_id] = task
        return task

    async def cleanup_session(self, item_id: str):
        """Cancel and clean up any running agent session for an item."""
        session = self.sessions.pop(item_id, None)
        agent_task = self._agent_tasks.pop(item_id, None)
        self._last_agent_messages.pop(item_id, None)
        self._commit_messages.pop(item_id, None)

        if session:
            try:
                await session.cancel()
            except Exception:
                pass

        if agent_task and not agent_task.done():
            agent_task.cancel()
            try:
                await agent_task
            except (asyncio.CancelledError, Exception):
                pass

    async def cleanup_all_sessions(self):
        """Gracefully stop all running agents."""
        item_ids = list(set(list(self.sessions.keys()) + list(self._agent_tasks.keys())))
        for item_id in item_ids:
            try:
                await self.cleanup_session(item_id)
            except Exception:
                pass

    def get_session(self, item_id: str) -> Optional[AgentSession]:
        """Get session for an item."""
        return self.sessions.get(item_id)

    def get_last_message(self, item_id: str) -> Optional[str]:
        """Get last message for an item."""
        return self._last_agent_messages.get(item_id)

    def set_commit_message(self, item_id: str, message: str) -> str:
        """Set commit message for an item."""
        self._commit_messages[item_id] = message
        return f"Commit message saved: {message}"

    def get_commit_message(self, item_id: str) -> Optional[str]:
        """Get commit message for an item."""
        return self._commit_messages.pop(item_id, None)

    def _parse_plugins(self, plugins_json: Optional[str]) -> Optional[List[Dict[str, Any]]]:
        """Parse plugins JSON string from config into a list of plugin configs."""
        if not plugins_json:
            return None
        try:
            plugins = json.loads(plugins_json) if isinstance(plugins_json, str) else plugins_json
            if not isinstance(plugins, list) or len(plugins) == 0:
                return None
            # Normalize: each entry can be a string (path) or dict with "path" key
            result = []
            for entry in plugins:
                if isinstance(entry, str) and entry.strip():
                    result.append({"type": "local", "path": entry.strip()})
                elif isinstance(entry, dict) and entry.get("path"):
                    result.append({"type": "local", "path": entry["path"]})
            return result if result else None
        except Exception as e:
            logger.warning(f"Failed to parse plugins config: {e}")
            return None