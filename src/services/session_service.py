"""Session service for managing agent session lifecycle."""

import asyncio
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..agent.profiles import resolve_ollama_env
from ..agent.session import AgentSession

logger = logging.getLogger(__name__)


class SessionService:
    """Manages agent sessions and their lifecycle."""

    def __init__(self):
        self.sessions: Dict[str, AgentSession] = {}
        self._agent_tasks: Dict[str, asyncio.Task] = {}  # item_id -> _run_agent task
        self._last_agent_messages: Dict[str, str] = {}  # item_id -> last agent text
        self._commit_messages: Dict[str, str] = {}  # item_id -> commit message from tool
        self._caffeinate_proc: Optional[subprocess.Popen] = None

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
                           on_request_command: Optional[Callable] = None,
                           on_request_tool: Optional[Callable] = None,
                           on_view_board: Optional[Callable] = None,
                           on_who_am_i: Optional[Callable] = None,
                           on_graph_query: Optional[Callable] = None,
                           on_delete_todo: Optional[Callable] = None,
                           on_create_epic: Optional[Callable] = None,
                           on_create_shortcut: Optional[Callable] = None,
                           workspace_root: Optional[Path] = None,
                           sibling_repo_paths: Optional[List[Path]] = None,
                           item_repo_name: Optional[str] = None,
                           epic_plan_relpath: Optional[str] = None,
                           use_chrome: bool = False) -> AgentSession:
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

        # config has already been parsed by db.get_agent_config (Phase 3),
        # so list/dict fields arrive as real Python types.
        plugins = self._parse_plugins(config.get("plugins"), config.get("enabled_skills"))
        allowed_commands = list(config.get("allowed_commands") or [])
        allowed_builtin_tools = list(config.get("allowed_builtin_tools") or [])

        # Ollama env only if enabled AND the model is actually an Ollama model
        # (Claude models must not be routed to Ollama) — see agent/profiles.py.
        ollama_env = resolve_ollama_env(config, session_model)

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
            on_request_tool=on_request_tool,
            on_view_board=on_view_board,
            on_who_am_i=on_who_am_i,
            on_graph_query=on_graph_query,
            graphify_enabled=bool(config.get("graphify_enabled", False)),
            on_delete_todo=on_delete_todo,
            on_create_epic=on_create_epic,
            on_create_shortcut=on_create_shortcut,
            mcp_servers=config.get("mcp_servers"),
            mcp_enabled=config.get("mcp_enabled", False),
            plugins=plugins,
            allowed_commands=allowed_commands,
            bash_yolo=config.get("bash_yolo", False),
            allowed_builtin_tools=allowed_builtin_tools,
            ollama_env=ollama_env,
            ollama_load_claude_md=bool(config.get("ollama_load_claude_md", False)),
            workspace_root=workspace_root,
            sibling_repo_paths=sibling_repo_paths,
            item_repo_name=item_repo_name,
            epic_plan_relpath=epic_plan_relpath,
            use_chrome=use_chrome,
            item_id=item_id,
        )

        self.sessions[item_id] = session
        self._update_caffeinate()
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

    async def pause_session(self, item_id: str) -> str | None:
        """Pause a running session — capture session_id, then cancel.

        Returns the session_id for later resumption, or None.
        """
        session = self.sessions.get(item_id)
        session_id = getattr(session, 'current_session_id', None) if session else None

        await self.cleanup_session(item_id)
        return session_id

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

        self._update_caffeinate()

    async def cleanup_all_sessions(self):
        """Gracefully stop all running agents."""
        item_ids = list(set(list(self.sessions.keys()) + list(self._agent_tasks.keys())))
        for item_id in item_ids:
            try:
                await self.cleanup_session(item_id)
            except Exception:
                pass
        self._stop_caffeinate()

    def remove_session(self, item_id: str):
        """Remove a finished session from tracking without cancelling it.

        Unlike cleanup_session(), this doesn't cancel the session or task —
        it just removes the dict entry so the session no longer counts as active.
        Safe to call from on_complete/on_error callbacks where the session
        has already finished naturally.
        """
        self.sessions.pop(item_id, None)
        self._update_caffeinate()

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

    def _update_caffeinate(self):
        """Start or stop caffeinate based on whether agents are running."""
        if self.sessions and not self._caffeinate_proc:
            self._start_caffeinate()
        elif not self.sessions and self._caffeinate_proc:
            self._stop_caffeinate()

    def _start_caffeinate(self):
        """Spawn caffeinate to prevent idle sleep (macOS only)."""
        if sys.platform != "darwin" or self._caffeinate_proc:
            return
        try:
            self._caffeinate_proc = subprocess.Popen(
                ["caffeinate", "-i"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info("caffeinate started — preventing idle sleep while agents run")
        except FileNotFoundError:
            pass

    def _stop_caffeinate(self):
        """Kill the caffeinate process."""
        if self._caffeinate_proc:
            self._caffeinate_proc.terminate()
            self._caffeinate_proc = None
            logger.info("caffeinate stopped — idle sleep re-enabled")

    def _parse_plugins(self, plugins: Optional[Any],
                       enabled_skills: Optional[Any] = None) -> Optional[List[Dict[str, Any]]]:
        """Merge auto-discovered plugins (from the dashboard's plugins/
        directory) with user-configured ones from agent config, plus the
        project's enabled library skills (skill-library/<name>).

        After Phase 3, `plugins` arrives as a real list (db.get_agent_config
        decodes JSON before handing it back). A string is still tolerated
        for legacy callers."""
        result = []
        root = Path(__file__).parent.parent.parent

        # Auto-discover plugins from the dashboard's plugins/ directory
        plugins_dir = root / "plugins"
        if plugins_dir.is_dir():
            for entry in sorted(plugins_dir.iterdir()):
                manifest = entry / ".claude-plugin" / "plugin.json"
                if entry.is_dir() and manifest.exists():
                    logger.info(f"Auto-discovered plugin: {entry.name} ({entry.resolve()})")
                    result.append({"type": "local", "path": str(entry.resolve())})

        # Tolerate a JSON string for callers that haven't migrated yet.
        if isinstance(plugins, str):
            try:
                plugins = json.loads(plugins) if plugins else []
            except (json.JSONDecodeError, TypeError):
                plugins = []

        if isinstance(plugins, list) and plugins:
            seen = {p["path"] for p in result}
            for entry in plugins:
                path = None
                if isinstance(entry, str) and entry.strip():
                    path = entry.strip()
                elif isinstance(entry, dict) and entry.get("path"):
                    path = entry["path"]
                if path and path not in seen:
                    result.append({"type": "local", "path": path})
                    seen.add(path)

        # Per-project enabled library skills (each is a one-skill plugin).
        if isinstance(enabled_skills, str):
            try:
                enabled_skills = json.loads(enabled_skills) if enabled_skills else []
            except (json.JSONDecodeError, TypeError):
                enabled_skills = []
        if isinstance(enabled_skills, list) and enabled_skills:
            seen = {p["path"] for p in result}
            library_dir = root / "skill-library"
            for name in enabled_skills:
                if not isinstance(name, str) or not name:
                    continue
                skill_dir = library_dir / name
                if (skill_dir / ".claude-plugin" / "plugin.json").exists():
                    path = str(skill_dir.resolve())
                    if path not in seen:
                        result.append({"type": "local", "path": path})
                        seen.add(path)

        if result:
            logger.info(f"Loaded {len(result)} plugin(s): {', '.join(p['path'].rsplit('/', 1)[-1] for p in result)}")
        return result if result else None