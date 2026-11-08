"""Session service for managing agent session lifecycle."""

import asyncio
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..agent.base import AbstractAgentSession
from ..agent.kimi_session import KimiAgentSession
from ..agent.profiles import is_kimi_model, load_claude_md_for, resolve_local_env
from ..agent.session import ClaudeAgentSession

logger = logging.getLogger(__name__)


class SessionService:
    """Manages agent sessions and their lifecycle."""

    def __init__(self):
        self.sessions: Dict[str, AbstractAgentSession] = {}
        self._agent_tasks: Dict[str, asyncio.Task] = {}  # item_id -> _run_agent task
        self._last_agent_messages: Dict[str, str] = {}  # item_id -> last agent text
        self._commit_messages: Dict[str, str] = {}  # item_id -> commit message from tool
        self._caffeinate_proc: Optional[subprocess.Popen] = None

    async def create_session(self, item_id: str, worktree_path: Path, config: Dict[str, Any],
                             model: Optional[str] = None, **options: Any) -> AbstractAgentSession:
        """Create a new agent session with all callbacks.

        ``options`` are the keyword options in ``SESSION_OPTION_DEFAULTS`` (the
        session callbacks plus the read-scope / per-item settings); any other
        keyword is a TypeError, as with an explicit signature.
        """
        opts = _session_options(options)
        # Use provided model or fall back to config model
        session_model = model or config.get("model")
        system_prompt = _system_prompt(config)

        # Create default message callback if none provided
        if not opts["on_message"]:
            async def default_on_message(text: str, iid: str = item_id):
                self._last_agent_messages[iid] = text

            opts["on_message"] = default_on_message

        # config has already been parsed by db.get_agent_config (Phase 3),
        # so list/dict fields arrive as real Python types.
        plugins = self._parse_plugins(config.get("plugins"), config.get("enabled_skills"))
        spec = {**opts, "item_id": item_id, "worktree_path": worktree_path,
                "model": session_model, "system_prompt": system_prompt, "plugins": plugins}

        # Kimi models run on a separate runtime (Kimi Agent SDK, experimental) —
        # a different session class, not a profile of the Claude runtime.
        if is_kimi_model(session_model):
            session = _kimi_session(config, spec)
        else:
            session = _claude_session(config, spec)
        self.sessions[item_id] = session
        self._update_caffeinate()
        return session

    async def start_session_task(self, item_id: str, session: AbstractAgentSession, prompt: str,
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

        await _cancel_quietly(session)
        await _stop_task(agent_task)
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

    def get_session(self, item_id: str) -> Optional[ClaudeAgentSession]:
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
        root = Path(__file__).parent.parent.parent
        result = [{"type": "local", "path": path} for path in _bundled_plugin_paths(root / "plugins")]
        seen = {p["path"] for p in result}
        extra_paths = _configured_plugin_paths(plugins) + _enabled_skill_paths(
            root / "skill-library", enabled_skills
        )
        for path in extra_paths:
            if path not in seen:
                result.append({"type": "local", "path": path})
                seen.add(path)

        if result:
            logger.info(f"Loaded {len(result)} plugin(s): {', '.join(p['path'].rsplit('/', 1)[-1] for p in result)}")
        return result if result else None


# Keyword options of SessionService.create_session, with their defaults: the
# callbacks a session reports through, then the read-scope / per-item settings.
SESSION_OPTION_DEFAULTS: Dict[str, Any] = {
    "on_message": None,
    "on_tool_use": None,
    "on_thinking": None,
    "on_complete": None,
    "on_error": None,
    "on_clarify": None,
    "on_create_todo": None,
    "on_set_commit_message": None,
    "on_request_command": None,
    "on_request_tool": None,
    "on_view_board": None,
    "on_who_am_i": None,
    "on_peek_worktree": None,
    "on_graph_query": None,
    "on_delete_todo": None,
    "on_create_epic": None,
    "on_create_shortcut": None,
    "workspace_root": None,        # Optional[Path] — multi-repo workspace root
    "sibling_repo_paths": None,    # Optional[List[Path]] — readable sibling repos
    "item_repo_name": None,        # Optional[str] — the item's repo (multi-repo)
    "epic_plan_relpath": None,     # Optional[str] — the epic's shared plan file
    "use_chrome": False,
}


def _session_options(options: Dict[str, Any]) -> Dict[str, Any]:
    """``options`` over ``SESSION_OPTION_DEFAULTS``; an unknown name is a TypeError."""
    unknown = [name for name in options if name not in SESSION_OPTION_DEFAULTS]
    if unknown:
        raise TypeError(f"SessionService.create_session() got an unexpected keyword argument '{unknown[0]}'")
    return {**SESSION_OPTION_DEFAULTS, **options}


def _system_prompt(config: Dict[str, Any]) -> str:
    """The configured system prompt, with the project context appended when set."""
    system_prompt = config.get("system_prompt", "") or ""
    project_context = config.get("project_context", "") or ""
    if project_context:
        system_prompt = f"{system_prompt}\n\nProject context:\n{project_context}"
    return system_prompt


def _claude_session(config: Dict[str, Any], spec: Dict[str, Any]) -> ClaudeAgentSession:
    """A Claude Agent SDK session (Claude models and the local Tiiny / Ollama profiles).

    ``spec`` is create_session's options plus item_id / worktree_path / model /
    system_prompt / plugins.
    """
    model = spec["model"]
    # Local-provider env (Tiiny or Ollama) only if that provider is enabled
    # AND the model belongs to it (Claude models must never be routed to a
    # local provider) — see agent/profiles.py.
    local_env = resolve_local_env(config, model)
    return ClaudeAgentSession(
        worktree_path=spec["worktree_path"],
        system_prompt=spec["system_prompt"],
        model=model,
        on_message=spec["on_message"],
        on_tool_use=spec["on_tool_use"],
        on_thinking=spec["on_thinking"],
        on_complete=spec["on_complete"],
        on_error=spec["on_error"],
        on_clarify=spec["on_clarify"],
        on_create_todo=spec["on_create_todo"],
        on_set_commit_message=spec["on_set_commit_message"],
        on_request_command=spec["on_request_command"],
        on_request_tool=spec["on_request_tool"],
        on_view_board=spec["on_view_board"],
        on_who_am_i=spec["on_who_am_i"],
        on_peek_worktree=spec["on_peek_worktree"],
        on_graph_query=spec["on_graph_query"],
        graphify_enabled=bool(config.get("graphify_enabled", False)),
        on_delete_todo=spec["on_delete_todo"],
        on_create_epic=spec["on_create_epic"],
        on_create_shortcut=spec["on_create_shortcut"],
        mcp_servers=config.get("mcp_servers"),
        mcp_enabled=config.get("mcp_enabled", False),
        plugins=spec["plugins"],
        allowed_commands=list(config.get("allowed_commands") or []),
        bash_yolo=config.get("bash_yolo", False),
        allowed_builtin_tools=list(config.get("allowed_builtin_tools") or []),
        local_env=local_env,
        load_claude_md=load_claude_md_for(config, model),
        workspace_root=spec["workspace_root"],
        sibling_repo_paths=spec["sibling_repo_paths"],
        item_repo_name=spec["item_repo_name"],
        epic_plan_relpath=spec["epic_plan_relpath"],
        use_chrome=spec["use_chrome"],
        item_id=spec["item_id"],
    )


def _kimi_session(config: Dict[str, Any], spec: Dict[str, Any]) -> KimiAgentSession:
    """A Kimi Agent SDK session (separate runtime; it takes a subset of the callbacks)."""
    return KimiAgentSession(
        worktree_path=spec["worktree_path"],
        system_prompt=spec["system_prompt"],
        model=spec["model"],
        on_message=spec["on_message"],
        on_tool_use=spec["on_tool_use"],
        on_thinking=spec["on_thinking"],
        on_complete=spec["on_complete"],
        on_error=spec["on_error"],
        on_set_commit_message=spec["on_set_commit_message"],
        on_clarify=spec["on_clarify"],
        on_request_command=spec["on_request_command"],
        allowed_commands=list(config.get("allowed_commands") or []),
        bash_yolo=config.get("bash_yolo", False),
        item_id=spec["item_id"],
        # Worktree boundary for the ACP permission handler; in
        # multi-repo mode the workspace root also unlocks reads.
        workspace_root=spec["workspace_root"],
    )


async def _cancel_quietly(session: Optional[AbstractAgentSession]) -> None:
    """Cancel a session, ignoring any error it raises while stopping."""
    if not session:
        return
    try:
        await session.cancel()
    except Exception:
        pass


async def _stop_task(task: Optional[asyncio.Task]) -> None:
    """Cancel a still-running task and wait for it to end."""
    if not task or task.done():
        return
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass


def _decode_json_list(value: Any) -> Any:
    """Decode a JSON string (legacy callers); anything else passes through.

    An empty or malformed string becomes [].
    """
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value) if value else []
    except (json.JSONDecodeError, TypeError):
        return []


def _bundled_plugin_paths(plugins_dir: Path) -> List[str]:
    """Plugins shipped in the dashboard's plugins/ directory (auto-discovered)."""
    if not plugins_dir.is_dir():
        return []
    paths = []
    for entry in sorted(plugins_dir.iterdir()):
        manifest = entry / ".claude-plugin" / "plugin.json"
        if entry.is_dir() and manifest.exists():
            logger.info(f"Auto-discovered plugin: {entry.name} ({entry.resolve()})")
            paths.append(str(entry.resolve()))
    return paths


def _configured_plugin_paths(plugins: Any) -> List[str]:
    """Plugin paths from agent config: a list of path strings or {"path": ...} dicts."""
    plugins = _decode_json_list(plugins)
    if not isinstance(plugins, list):
        return []
    paths = []
    for entry in plugins:
        if isinstance(entry, str) and entry.strip():
            paths.append(entry.strip())
        elif isinstance(entry, dict) and entry.get("path"):
            paths.append(entry["path"])
    return paths


def _enabled_skill_paths(library_dir: Path, enabled_skills: Any) -> List[str]:
    """The project's enabled library skills that are installed (each a one-skill plugin)."""
    enabled_skills = _decode_json_list(enabled_skills)
    if not isinstance(enabled_skills, list):
        return []
    paths = []
    for name in enabled_skills:
        if not isinstance(name, str) or not name:
            continue
        skill_dir = library_dir / name
        if (skill_dir / ".claude-plugin" / "plugin.json").exists():
            paths.append(str(skill_dir.resolve()))
    return paths
