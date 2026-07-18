import asyncio
import json
import logging
import os
import re
import signal
import subprocess as _subprocess
from pathlib import Path

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    UserMessage,
    SystemMessage,
    ResultMessage,
    StreamEvent,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
    ServerToolUseBlock,
    ServerToolResultBlock,
    ThinkingBlock,
    HookMatcher,
    PermissionResultAllow,
    PermissionResultDeny,
)

from .base import AbstractAgentSession, AgentResult  # noqa: F401  (AgentResult re-exported)
from .profiles import profile_options_kwargs, resolve_profile

logger = logging.getLogger(__name__)


def _server_result_text(content) -> str:
    """Flatten a ServerToolResultBlock's content into displayable text.

    Server tool results (advisor analysis, web_search, etc.) arrive as either
    a plain string or a list of content blocks/dicts. Pull out any text so it
    isn't silently dropped.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(item.get("text") or item.get("content") or "")
            else:
                parts.append(getattr(item, "text", "") or "")
        return "\n".join(p for p in parts if p).strip()
    return str(content).strip()


_ANNOTATION_PREFIX_RE = re.compile(r"^(annotation_\d+)_(original|annotated)\.jpg$")


def build_attachment_prompt(attachments: list[dict]) -> str:
    """Build prompt text describing attached images.

    Groups paired annotation files (original + annotations overlay) and
    includes annotation summaries. Plain attachments are listed individually.
    """
    if not attachments:
        return ""

    # Group by annotation timestamp prefix
    groups: dict[str, dict] = {}  # prefix -> {"original": ..., "annotations": ..., "summary": ...}
    ungrouped: list[dict] = []

    for att in attachments:
        m = _ANNOTATION_PREFIX_RE.match(att["filename"])
        if m:
            prefix = m.group(1)
            kind = m.group(2)
            if prefix not in groups:
                groups[prefix] = {}
            groups[prefix][kind] = att["dest"]
            if att.get("annotation_summary"):
                groups[prefix]["summary"] = att["annotation_summary"]
        else:
            ungrouped.append(att)

    lines = []

    # Render grouped annotation pairs
    for prefix, group in groups.items():
        if "original" in group and "annotated" in group:
            lines.append("The following annotated screenshot is attached:")
            lines.append(f"- {group['original']} (clean screenshot without annotations)")
            lines.append(f"- {group['annotated']} (same screenshot with annotation markers drawn on it)")
            if "summary" in group:
                lines.append(f"- Annotations: {group['summary']}")
        else:
            # Unpaired — treat as simple attachment
            dest = group.get("original") or group.get("annotated")
            if dest:
                ungrouped.append({"dest": dest})

    # Render ungrouped / plain attachments
    if ungrouped:
        if lines:
            lines.append("")
        lines.append("Attached reference images (use Read tool to view):")
        for att in ungrouped:
            lines.append(f"- {att['dest']}")

    if lines:
        lines.append("")
        lines.append(
            "IMPORTANT: Before making any changes, study the attached images carefully. "
            "Describe what you see and what the annotations are highlighting. "
            "If anything is unclear, use ask_user to confirm your understanding."
        )

    return "\n".join(lines)


class AgentSession(AbstractAgentSession):
    """Wraps a ClaudeSDKClient for a single item's agent run."""

    def __init__(
        self,
        worktree_path: Path,
        system_prompt: str,
        model: str | None = None,
        on_message=None,
        on_tool_use=None,
        on_thinking=None,
        on_complete=None,
        on_error=None,
        on_clarify=None,
        on_create_todo=None,
        on_set_commit_message=None,
        on_request_command=None,
        on_request_tool=None,
        on_view_board=None,
        on_who_am_i=None,
        on_delete_todo=None,
        on_create_epic=None,
        on_create_shortcut=None,
        on_graph_query=None,
        graphify_enabled: bool = False,
        mcp_servers: str | None = None,
        mcp_enabled: bool = False,
        plugins: list[dict] | None = None,
        allowed_commands: list[str] | None = None,
        bash_yolo: bool = False,
        allowed_builtin_tools: list[str] | None = None,
        use_chrome: bool = False,
        ollama_env: dict[str, str] | None = None,
        ollama_load_claude_md: bool = False,
        workspace_root: Path | None = None,
        sibling_repo_paths: list[Path] | None = None,
        item_repo_name: str | None = None,
        item_id: str | None = None,
        epic_plan_relpath: str | None = None,
    ):
        self.worktree_path = worktree_path
        self.system_prompt = system_prompt
        self.model = model
        self.allowed_commands = allowed_commands or []
        self.bash_yolo = bash_yolo
        self.allowed_builtin_tools = allowed_builtin_tools or []
        self.ollama_env = ollama_env
        # When True, inject the worktree CLAUDE.md into the Ollama system prompt
        # (the Ollama path uses setting_sources=["local"], which does not
        # auto-load it the way the Claude path's ["project"] does).
        self.ollama_load_claude_md = ollama_load_claude_md
        # Multi-repo mode fields (all None in single-repo mode).
        self.workspace_root = workspace_root
        self.sibling_repo_paths = sibling_repo_paths or []
        self.item_repo_name = item_repo_name
        # The board item this agent is working on (used to tell the agent its own
        # ID in the system prompt and to back the who_am_i tool).
        self.item_id = item_id
        # Repo-relative path of this item's epic shared plan (None if no epic).
        self.epic_plan_relpath = epic_plan_relpath
        self.on_message = on_message        # async callback(text: str)
        self.on_tool_use = on_tool_use      # async callback(tool_name: str, input: dict)
        self.on_thinking = on_thinking      # async callback(thinking: str)
        self.on_complete = on_complete      # async callback(result: AgentResult)
        self.on_error = on_error            # async callback(error: str)
        self.on_clarify = on_clarify        # async callback(prompt: str, choices: list|None) -> str
        self.on_create_todo = on_create_todo  # async callback(title: str, description: str) -> dict
        self.on_set_commit_message = on_set_commit_message  # async callback(message: str) -> str
        self.on_request_command = on_request_command  # async callback(command: str, reason: str) -> str
        self.on_request_tool = on_request_tool      # async callback(tool_name: str, reason: str) -> str
        self.on_view_board = on_view_board          # async callback() -> str
        self.on_who_am_i = on_who_am_i              # async callback() -> dict (this agent's own item)
        self.on_graph_query = on_graph_query        # async callback(question: str) -> str
        self.graphify_enabled = graphify_enabled    # expose graph_query tool to the agent
        self.on_delete_todo = on_delete_todo        # async callback(item_id: str) -> str
        self.on_create_epic = on_create_epic        # async callback(title: str, color: str) -> dict
        self.on_create_shortcut = on_create_shortcut  # async callback(name: str, command: str) -> dict
        self.mcp_servers = mcp_servers      # JSON string of MCP server configurations from agent config
        self.mcp_enabled = mcp_enabled      # Whether MCP is enabled from agent config
        self.plugins = plugins              # List of plugin configs: [{"type": "local", "path": "..."}]
        self.use_chrome = use_chrome        # Launch claude --chrome (browser tools)
        self.client: ClaudeSDKClient | None = None
        self._task: asyncio.Task | None = None
        self._cancelled = False
        self.current_session_id: str | None = None
        self._subprocess_pid: int | None = None  # PID of the claude CLI subprocess

    async def start(self, prompt: str, attachments: list[dict] | None = None, resume_session_id: str | None = None) -> None:
        """Start the agent with a prompt and optional image attachments."""
        from .clarification import create_clarification_server
        from .todo import create_todo_server
        from .commit_message import create_commit_message_server

        mcp_servers = {}
        if self.on_clarify:
            mcp_servers["clarification"] = create_clarification_server(self.on_clarify)
        if self.on_create_todo:
            mcp_servers["todo"] = create_todo_server(self.on_create_todo, self.on_delete_todo, self.on_create_epic)
        if self.on_set_commit_message:
            mcp_servers["commit_message"] = create_commit_message_server(self.on_set_commit_message)
        if self.on_request_command:
            from .command_access import create_command_access_server
            mcp_servers["command_access"] = create_command_access_server(self.on_request_command)
        if self.on_request_tool:
            from .tool_access import create_tool_access_server
            mcp_servers["tool_access"] = create_tool_access_server(self.on_request_tool)
        if self.on_view_board:
            from .board_view import create_board_view_server
            mcp_servers["board_view"] = create_board_view_server(self.on_view_board)
        if self.on_who_am_i:
            from .who_am_i import create_who_am_i_server
            mcp_servers["who_am_i"] = create_who_am_i_server(self.on_who_am_i)
        if self.on_create_shortcut:
            from .shortcut import create_shortcut_server
            mcp_servers["shortcut"] = create_shortcut_server(self.on_create_shortcut)

        # Provider profile: which SDK options and features this run gets.
        # The Ollama profile disables heavy features (graphify, external MCP,
        # plugins, chrome) whose tool definitions overwhelm small local models.
        profile = resolve_profile(self.ollama_env, ollama_load_claude_md=self.ollama_load_claude_md)
        # graphify graph_query tool — only when enabled in config
        if self.on_graph_query and self.graphify_enabled and profile.graphify:
            from .graph_query import create_graph_query_server
            mcp_servers["graph_query"] = create_graph_query_server(self.on_graph_query)
        # External MCP servers from agent configuration (database)
        if self.mcp_enabled and self.mcp_servers and profile.external_mcp:
            # mcp_servers arrives as a parsed dict; tolerate a JSON
            # string for legacy callers.
            agent_mcp_servers = self.mcp_servers
            if isinstance(agent_mcp_servers, str):
                try:
                    agent_mcp_servers = json.loads(agent_mcp_servers)
                except Exception as e:
                    logger.warning(f"Failed to parse MCP servers from agent config: {e}")
                    agent_mcp_servers = {}
            if isinstance(agent_mcp_servers, dict) and agent_mcp_servers:
                mcp_servers.update(agent_mcp_servers)
                logger.info(f"Loaded {len(agent_mcp_servers)} MCP servers from agent configuration")
        elif self.mcp_enabled and self.mcp_servers:
            logger.info("Ollama mode: skipping external MCP servers to reduce context size")

        # Ensure agent knows to work in the worktree directory
        cwd_note = (
            f"\n\nIMPORTANT: Your working directory is {self.worktree_path}. "
            "All file operations must be within this directory."
            "\n\nThis directory is a git worktree — an isolated copy of the target project. "
            "Your changes here will be merged back to the main branch when your task is done. "
            "Other agents working on other tasks have their own separate worktrees. "
            "Always use relative paths or paths within this worktree — never reference "
            "other worktrees or the main project checkout directly."
        )

        # Multi-repo reference preamble: list sibling repos as read-only refs
        # and append parent-workspace CLAUDE.md / AGENTS.md contents.
        multi_repo_note = ""
        if self.workspace_root and self.sibling_repo_paths:
            repo_lines = "\n".join(f"- {p}" for p in self.sibling_repo_paths)
            multi_repo_note = (
                f"\n\nMULTI-REPO WORKSPACE: You are working on `{self.item_repo_name or 'this repo'}`."
                f" Your worktree is {self.worktree_path}."
                f"\nThe workspace root {self.workspace_root} contains sibling repos you MAY READ"
                f" but MUST NOT edit:\n{repo_lines}\n"
                "Use Read/Glob/Grep on these paths to consult related code (shared protocols,"
                " types, conventions) when useful. Do NOT use Edit/Write/Bash to modify them —"
                " they are owned by other items on the board. If you need a change in a"
                " sibling repo, call mcp__todo__create_todo to propose a new item targeting"
                " that repo instead."
            )
            # Append parent CLAUDE.md / AGENTS.md (if present) so workspace-wide
            # conventions reach the agent — the SDK's setting_sources=["project"]
            # only reads from cwd, which is the worktree.
            for fname in ("CLAUDE.md", "AGENTS.md"):
                fpath = self.workspace_root / fname
                try:
                    if fpath.is_file():
                        content = fpath.read_text(errors="replace")
                        multi_repo_note += (
                            f"\n\n--- Workspace {fname} ({fpath}) ---\n{content}"
                        )
                except Exception as e:
                    logger.warning(f"Could not read workspace {fname} at {fpath}: {e}")
        board_item_note = ""
        if self.item_id:
            board_item_note = (
                f"\n\nYOUR BOARD ITEM: you are working on board item `{self.item_id}`. "
                "Call the who_am_i tool (mcp__who_am_i__who_am_i) any time for your full "
                "item details (title, column, dependencies). Use this ID when a follow-up "
                "task must wait for you — pass it in the `requires` field of create_todo. "
                "You never need to guess which card is yours from view_board."
            )
        clarify_note = (
            "\n\nIMPORTANT: If you need to ask the user a question or need clarification, "
            "you MUST use the ask_user MCP tool (mcp__clarification__ask_user). "
            "Do NOT use ToolSearch, AskUserQuestion, or any other built-in tool to ask questions. "
            "The ask_user tool is the ONLY way to communicate with the user."
        )
        commit_note = (
            "\n\nIMPORTANT: When you have finished your task, you MUST call the "
            "set_commit_message tool with a concise commit message summarizing what you did. "
            "Use conventional style: start with a verb (Add, Fix, Update, Refactor, Remove). "
            "This is required — do not skip it."
        )
        # Task lifecycle: weak/local models otherwise invent a manual "close the
        # card" procedure (TaskUpdate/TaskStop/inloop, or spawning child todos to
        # mark their own work done) and burn the whole budget flailing. Completion
        # is automatic — they just need to stop.
        lifecycle_note = (
            "\n\nIMPORTANT — how a task finishes: When your work is done, simply write your "
            "final message and call set_commit_message. That is all. The system AUTOMATICALLY "
            "moves this card from Doing to Done and merges your worktree when your turn ends — "
            "you do NOT move, close, approve, or update the card yourself.\n"
            "- Do NOT use TaskUpdate, TaskGet, TaskStop, TaskList, TaskCreate, or any mcp__inloop__* "
            "tool to manage your own item — they do not control this board and will fail or do nothing.\n"
            "- Do NOT create a new todo for the work you are already doing (e.g. a 'verify my own fix' "
            "item). Use mcp__todo__create_todo ONLY for genuinely new, separate future work.\n"
            "- If your work is finished, STOP. Do not keep calling tools to confirm completion."
        )
        if profile.lifecycle_addendum:
            lifecycle_note += (
                "\n\nTO FINISH THIS TASK: stop calling tools. Write one short final message, call "
                "set_commit_message once, and end your turn. Do nothing else. The card moves to Done "
                "by itself. Never spawn another todo to finish or verify your own work."
                "\n\nBE DECISIVE: For a simple factual query, run ONE command to get the answer and "
                "then proceed. Trust the output you see — do not re-run the same command in different "
                "ways or exhaust every interpretation. State your assumptions clearly instead of "
                "verifying them repeatedly."
            )
        todo_note = (
            "\n\nIMPORTANT: To create todo items on the board, you MUST use the create_todo MCP tool "
            "(mcp__todo__create_todo). Do NOT use TodoWrite, TaskCreate, or any other built-in tool "
            "for creating todos — those are internal tools that do not add items to the board. "
            "To delete a todo item, use mcp__todo__delete_todo. "
            "To create an epic for grouping related todos, use mcp__todo__create_epic. "
            "To see existing board items, use mcp__board_view__view_board."
            "\n\nIMPORTANT: When creating todos that have logical dependencies, you MUST use the "
            "'requires' parameter to specify which item IDs must be completed first. "
            "For example, if task B depends on task A, create task A first, note its ID, "
            "then create task B with requires=[\"<task-A-id>\"]. "
            "To make a task depend on YOU (so it waits for your own work to merge), use "
            "your own item ID — get it from the who_am_i tool (mcp__who_am_i__who_am_i). "
            "Always think about task ordering \u2014 even in parallel workflows, some tasks "
            "naturally depend on others (e.g., UI components depend on layout structure, "
            "integration tasks depend on the pieces they integrate)."
        )
        command_note = (
            "\n\nIf a shell command is blocked, use the request_command_access tool "
            "to ask the user for permission. Provide the command name and reason."
        )
        tool_note = (
            "\n\nIf a built-in tool (like WebSearch or WebFetch) is blocked, use the "
            "mcp__tool_access__request_tool_access tool to ask the user for permission. "
            "Do NOT use ToolSearch to find it — call it directly."
        )
        brainstorm_note = (
            "\n\nIMPORTANT: If the task description contains words like 'brainstorm', 'explore', "
            "'design', 'plan', 'ideas', or 'suggest' — this is a BRAINSTORMING task, not an implementation task. "
            "Do NOT write code or make changes. Instead:\n"
            "1. Use mcp__board_view__view_board to see existing work\n"
            "2. Use mcp__clarification__ask_user to ask clarifying questions ONE AT A TIME\n"
            "3. Propose 2-3 approaches and ask the user to pick one\n"
            "4. Once the user approves a design, create an Epic (mcp__todo__create_epic) and "
            "Todos (mcp__todo__create_todo) on the board — do NOT implement the tasks yourself\n"
            "5. Set a commit message summarizing the plan"
        )
        debug_note = (
            "\n\nIMPORTANT: If the task is about fixing a bug, debugging, or troubleshooting — "
            "do NOT guess at fixes. Investigate first:\n"
            "1. Read the full error message/stack trace\n"
            "2. Reproduce the issue and trace the data flow to find root cause\n"
            "3. Find similar working code and compare\n"
            "4. Form a specific hypothesis, test with the smallest possible change\n"
            "5. If stuck after 3 attempts, use mcp__clarification__ask_user to explain what you tried"
        )
        # Chrome browser integration is launched via the `claude --chrome` flag
        # below. Skip it in Ollama mode — small local models are overwhelmed by
        # the extra browser tool definitions.
        chrome_enabled = self.use_chrome and profile.chrome
        browser_note = ""
        if chrome_enabled:
            browser_note = (
                "\n\nYou have access to a web browser via the Claude-in-Chrome tools "
                "(mcp__claude-in-chrome__*): navigate to URLs, read page content, inspect "
                "the DOM, take screenshots, fill forms, and read the console/network. Use "
                "them whenever the task involves the web, a running UI, or anything you need "
                "to see in a browser. The browser shares the user's Chrome session — be "
                "careful with any destructive or authenticated actions."
            )

        graph_note = ""
        if "graph_query" in mcp_servers:
            graph_note = (
                "\n\nThis project has a knowledge graph of its code. Before editing "
                "unfamiliar code, use mcp__graph_query__graph_query to orient — ask what "
                "calls a function, where a concept lives, or how a flow connects. "
                "Answers cite source locations you can open."
            )

        # Ollama agents run with setting_sources=["local"], which does NOT
        # auto-load the project CLAUDE.md (the Claude path's ["project"] does).
        # When the Ollama "Load project CLAUDE.md" toggle is on, inject the
        # worktree CLAUDE.md into the system prompt so project conventions reach
        # the local model.
        claude_md_note = ""
        if profile.inject_claude_md:
            claude_md_path = self.worktree_path / "CLAUDE.md"
            try:
                if claude_md_path.is_file():
                    content = claude_md_path.read_text(errors="replace")
                    claude_md_note = (
                        f"\n\n--- Project CLAUDE.md ({claude_md_path}) ---\n{content}"
                    )
                    logger.info("Ollama mode: injected project CLAUDE.md into system prompt")
                else:
                    logger.info("Ollama 'Load project CLAUDE.md' is on but no CLAUDE.md found in worktree")
            except Exception as e:
                logger.warning(f"Could not read project CLAUDE.md at {claude_md_path}: {e}")

        # Shared project plan: a fanned-out multi-agent build keeps one source of
        # truth (project-plan.md at the repo / workspace root). Rather than make
        # every task description repeat "read the plan first, update it before
        # finishing", surface that convention here for any agent whose checkout
        # carries the file. (worktree first, then the workspace root in multi-repo.)
        shared_plan_note = ""
        plan_roots = [self.worktree_path]
        if self.workspace_root:
            plan_roots.append(self.workspace_root)
        for plan_root in plan_roots:
            try:
                plan_path = plan_root / "project-plan.md"
                if plan_path.is_file():
                    shared_plan_note = (
                        f"\n\nSHARED PROJECT PLAN: this project has a shared plan at "
                        f"{plan_path}. READ IT FIRST to understand the goal, milestones, "
                        "decisions, and current state before you start. BEFORE you finish, "
                        "update its 'Current state' and 'Decisions' sections to reflect what "
                        "you did. It is the single source of truth shared across every task — "
                        "keep it accurate so the next agent picks up where you left off."
                    )
                    break
            except Exception as e:
                logger.warning(f"Could not check for shared plan at {plan_root}: {e}")

        # Epic-scoped plan: this item belongs to an epic, so point it at that
        # epic's plan in addition to the project-wide one above.
        epic_plan_note = ""
        if self.epic_plan_relpath:
            for plan_root in plan_roots:
                try:
                    epic_plan_path = plan_root / self.epic_plan_relpath
                    if epic_plan_path.is_file():
                        epic_plan_note = (
                            f"\n\nEPIC PLAN: your task belongs to an epic whose shared plan "
                            f"is at {epic_plan_path}. This is the detailed plan for your "
                            "workstream — read it first and update its 'Current state' and "
                            "'Decisions' before you finish, alongside the project-wide plan."
                        )
                        break
                except Exception as e:
                    logger.warning(f"Could not check for epic plan at {plan_root}: {e}")

        full_system_prompt = (self.system_prompt or "") + cwd_note + board_item_note + multi_repo_note + shared_plan_note + epic_plan_note + clarify_note + commit_note + lifecycle_note + todo_note + brainstorm_note + debug_note + command_note + tool_note + browser_note + graph_note + claude_md_note

        # Configure allowed MCP tools
        allowed_tools = []
        if "clarification" in mcp_servers:
            allowed_tools.append("mcp__clarification__ask_user")
        if "todo" in mcp_servers:
            allowed_tools.append("mcp__todo__create_todo")
            allowed_tools.append("mcp__todo__delete_todo")
            allowed_tools.append("mcp__todo__create_epic")
        if "commit_message" in mcp_servers:
            allowed_tools.append("mcp__commit_message__set_commit_message")
        if "command_access" in mcp_servers:
            allowed_tools.append("mcp__command_access__request_command_access")
        if "tool_access" in mcp_servers:
            allowed_tools.append("mcp__tool_access__request_tool_access")
        if "board_view" in mcp_servers:
            allowed_tools.append("mcp__board_view__view_board")
        if "who_am_i" in mcp_servers:
            allowed_tools.append("mcp__who_am_i__who_am_i")
        if "shortcut" in mcp_servers:
            allowed_tools.append("mcp__shortcut__create_shortcut")
        if "graph_query" in mcp_servers:
            allowed_tools.append("mcp__graph_query__graph_query")

        # Allow all tools from external MCP servers (using wildcard for each server)
        for server_name, server_config in mcp_servers.items():
            if server_name not in ["clarification", "todo", "commit_message", "command_access", "tool_access", "board_view", "who_am_i", "shortcut", "graph_query"]:  # Skip our built-in servers
                allowed_tools.append(f"mcp__{server_name}__*")
                logger.info(f"Allowing all tools from external MCP server: {server_name}")

        # Allow the Claude-in-Chrome browser tools when chrome is enabled. The
        # `claude --chrome` flag (set in the SDK options below) registers this
        # MCP server at the CLI level, so it never appears in `mcp_servers`.
        if chrome_enabled:
            allowed_tools.append("mcp__claude-in-chrome__*")
            logger.info("Chrome integration enabled: allowing mcp__claude-in-chrome__* tools")

        # Build plugins list from configured plugin paths
        # Skip plugins for Ollama — they add many tool definitions that
        # overwhelm small local models.
        plugins = None
        plugin_prefixes = []
        if self.plugins and profile.plugins:
            plugins = []
            for plugin_config in self.plugins:
                plugin_path = plugin_config.get("path", "")
                if plugin_path:
                    plugins.append({"type": "local", "path": plugin_path})
                    plugin_name = Path(plugin_path).name
                    plugin_prefixes.append(f"mcp__plugin_{plugin_name}")
                    logger.info(f"Loading plugin from: {plugin_path}")
        elif self.plugins:
            logger.info("Ollama mode: skipping plugins to reduce context size")

        # Always allow Bash in the tool whitelist — permission_mode and the
        # PreToolUse hook handle actual command filtering.
        allowed_tools.append("Bash")

        # Always add optional built-in tools to the whitelist — the PreToolUse
        # hook filters disabled ones and directs the agent to request access.
        from .tool_filter import OPTIONAL_TOOL_NAMES
        for tool_name in OPTIONAL_TOOL_NAMES:
            if tool_name not in allowed_tools:
                allowed_tools.append(tool_name)

        hooks = None
        hook_matchers = []

        if not self.bash_yolo and self.allowed_commands:
            from .command_filter import make_command_filter_hook
            hook_matchers.append(
                HookMatcher(
                    matcher="Bash",
                    hooks=[make_command_filter_hook(self.allowed_commands, session=self)],
                )
            )

        # Add tool filter hook for optional built-in tools
        from .tool_filter import make_tool_filter_hook
        for tool_name in OPTIONAL_TOOL_NAMES:
            hook_matchers.append(
                HookMatcher(
                    matcher=tool_name,
                    hooks=[make_tool_filter_hook(self.allowed_builtin_tools)],
                )
            )

        # Add path guard hook to prevent agents from editing main repo.
        # In multi-repo mode, workspace_root unlocks reads to sibling repos.
        from .path_guard import make_path_guard_hook
        path_guard_hook = make_path_guard_hook(
            self.worktree_path, workspace_root=self.workspace_root,
        )
        for guarded_tool in ['Read', 'Edit', 'Write', 'Glob', 'Grep', 'Bash']:
            hook_matchers.append(
                HookMatcher(
                    matcher=guarded_tool,
                    hooks=[path_guard_hook],
                )
            )

        if hook_matchers:
            hooks = {"PreToolUse": hook_matchers}

        # Collect external MCP server prefixes (SDK wildcards don't work)
        external_mcp_prefixes = []
        for server_name, server_config in mcp_servers.items():
            if server_name not in ["clarification", "todo", "commit_message", "command_access", "tool_access", "board_view", "shortcut"]:
                external_mcp_prefixes.append(f"mcp__{server_name}__")

        # Build can_use_tool callback to allow plugin and external MCP tools
        # by prefix match, since SDK wildcard patterns don't work.
        # The CLI-registered Chrome MCP server's wildcard isn't honored by the
        # SDK either, so allow its tools by prefix in can_use_tool too.
        chrome_prefixes = ["mcp__claude-in-chrome__"] if chrome_enabled else []

        can_use_tool_fn = None
        all_prefixes = plugin_prefixes + external_mcp_prefixes + chrome_prefixes
        if all_prefixes:
            allowed_set = set(allowed_tools) if allowed_tools else set()
            async def can_use_tool(tool_name: str, *args):
                if tool_name in allowed_set:
                    return PermissionResultAllow()
                for prefix in all_prefixes:
                    if tool_name.startswith(prefix):
                        return PermissionResultAllow()
                # Allow standard (non-MCP) tools — permission_mode handles them
                if not tool_name.startswith("mcp__"):
                    return PermissionResultAllow()
                return PermissionResultDeny()
            can_use_tool_fn = can_use_tool

        # Provider-divergent SDK options (permission_mode, thinking,
        # setting_sources, env, stderr) come from the profile — the Ollama
        # rationale (thinking disabled, no `user` settings) is documented in
        # profiles.resolve_profile and locked in project-plan.md Decisions.
        if profile.name == "ollama":
            logger.info(f"Ollama mode: using lightweight SDK options for model {self.model}")
            logger.info(f"Ollama env: {self.ollama_env}")

        options_kwargs = dict(
            cwd=self.worktree_path,
            system_prompt=full_system_prompt,
            model=self.model,
            mcp_servers=mcp_servers if mcp_servers else None,
            allowed_tools=allowed_tools if allowed_tools else None,
            can_use_tool=can_use_tool_fn,
            add_dirs=[str(self.worktree_path), *(str(p) for p in self.sibling_repo_paths)],
            plugins=plugins if plugins else None,
            hooks=hooks,
            **profile_options_kwargs(profile),
        )
        if profile.allow_chrome_extra_args:
            # `--chrome` registers the Claude-in-Chrome MCP server and its
            # browser tools. Enabled per-task via the item's use_chrome flag.
            options_kwargs["extra_args"] = {"chrome": None} if chrome_enabled else {}
        options = ClaudeAgentOptions(**options_kwargs)

        if resume_session_id:
            options.resume = resume_session_id
            options.continue_conversation = True

        self.client = ClaudeSDKClient(options=options)
        await self.client.connect()

        # Capture subprocess PID for reliable cleanup — the SDK may null
        # its transport reference during disconnect(), making PID-based kill
        # the only reliable fallback.
        self._capture_subprocess_pid()

        # Check MCP server status and report issues
        await self._check_mcp_status()

        self._task = asyncio.create_task(self._receive_loop())

        # Copy attachments into worktree and reference in prompt
        if attachments:
            import shutil
            attach_dir = self.worktree_path / ".agent-attachments"
            attach_dir.mkdir(exist_ok=True)
            # Gitignore the attachments directory so they never get committed
            gitignore = attach_dir / ".gitignore"
            if not gitignore.exists():
                gitignore.write_text("*\n")
            processed = []
            for attachment in attachments:
                try:
                    asset_path = Path(attachment["asset_path"])
                    if asset_path.exists():
                        dest = attach_dir / attachment["filename"]
                        shutil.copy2(asset_path, dest)
                        processed.append({
                            "filename": attachment["filename"],
                            "dest": str(dest),
                            "annotation_summary": attachment.get("annotation_summary"),
                        })
                        logger.info(f"Copied attachment to worktree: {attachment['filename']}")
                except Exception as e:
                    logger.warning(f"Failed to copy attachment {attachment.get('filename', 'unknown')}: {e}")
            attachment_prompt = build_attachment_prompt(processed)
            if attachment_prompt:
                prompt += "\n\n" + attachment_prompt

        await self.client.query(prompt)

    async def _receive_loop(self) -> None:
        """Process messages from the agent."""
        # Capture client reference so finally block can disconnect even if
        # on_complete callback nulls self.client (e.g., via cancel())
        client_ref = self.client
        try:
            async for message in self.client.receive_messages():
                if self._cancelled:
                    break

                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            if self.on_message:
                                await self.on_message(block.text)
                        elif isinstance(block, ThinkingBlock):
                            if self.on_thinking and block.thinking:
                                await self.on_thinking(block.thinking)
                        elif isinstance(block, ToolUseBlock):
                            if self.on_tool_use:
                                await self.on_tool_use(block.name, block.input)
                        elif isinstance(block, ServerToolUseBlock):
                            # Server-executed tool call (advisor, web_search).
                            # Previously dropped — surface it like any tool use.
                            if self.on_tool_use:
                                await self.on_tool_use(block.name, block.input)
                        elif isinstance(block, ServerToolResultBlock):
                            # Result of a server-executed tool (e.g. advisor
                            # analysis). Previously dropped, causing messages
                            # carrying only server-side calls to arrive empty.
                            if self.on_message:
                                text = _server_result_text(block.content)
                                if text:
                                    await self.on_message(f"[advisor] {text}")

                elif isinstance(message, ResultMessage):
                    # Capture session_id
                    if message.session_id:
                        self.current_session_id = message.session_id

                    # Extract token usage from the usage dict
                    input_tokens = None
                    output_tokens = None
                    total_tokens = None

                    usage = message.usage or {}
                    if usage:
                        input_tokens = usage.get("input_tokens") or usage.get("input_token_count")
                        output_tokens = usage.get("output_tokens") or usage.get("output_token_count")
                        total_tokens = usage.get("total_tokens") or usage.get("total_token_count")

                    # Calculate total if not provided but components are
                    if total_tokens is None and input_tokens is not None and output_tokens is not None:
                        total_tokens = input_tokens + output_tokens

                    # HTTP status of a failing API call (429/500/529, etc.).
                    # Lets callers distinguish transient API errors from agent
                    # or task failures, and prefix the error for clarity.
                    api_error_status = getattr(message, "api_error_status", None)
                    if not isinstance(api_error_status, int):
                        api_error_status = None
                    error_text = message.result if message.is_error else None
                    if message.is_error and api_error_status:
                        error_text = f"[HTTP {api_error_status}] {error_text or ''}".strip()

                    result = AgentResult(
                        success=not message.is_error,
                        session_id=message.session_id,
                        cost_usd=message.total_cost_usd,
                        error=error_text,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        total_tokens=total_tokens,
                        api_error_status=api_error_status,
                    )
                    if self.on_complete:
                        await self.on_complete(result)
                    return

                elif isinstance(message, SystemMessage):
                    # Log system messages (progress, etc.)
                    if self.on_message and hasattr(message, 'content'):
                        text = str(message.content) if message.content else ""
                        if text:
                            await self.on_message(f"[system] {text}")

        except Exception as e:
            logger.exception("Agent session error")
            if self.on_error:
                await self.on_error(str(e))
        finally:
            # Clean up client connection — use captured reference since
            # self.client may have been set to None by cancel()
            self.client = None
            if client_ref:
                try:
                    await client_ref.disconnect()
                except Exception:
                    pass

            # Last-resort: force-kill by saved PID if process somehow survived
            self._force_kill_subprocess()

    async def send_message(self, text: str) -> None:
        """Send a follow-up message to the agent (e.g., clarification response)."""
        if self.client:
            await self.client.query(text)

    async def _check_mcp_status(self) -> None:
        """Check MCP server connection status and report issues."""
        if not self.client:
            return
        try:
            status = await self.client.get_mcp_status()
            servers = status.get("mcpServers", [])
            for server in servers:
                name = server.get("name", "unknown")
                state = server.get("status", "unknown")
                if state in ("failed", "disconnected", "needs-auth"):
                    error_msg = server.get("error", "")
                    msg = f"MCP server '{name}' {state}"
                    if error_msg:
                        msg += f": {error_msg}"
                    logger.warning(msg)
                    if self.on_message:
                        await self.on_message(f"[warning] {msg}")
                    try:
                        from ..web.routes import add_notification
                        add_notification("error", msg, source=f"mcp:{name}")
                    except Exception:
                        pass
                elif state == "connected":
                    tools = server.get("tools", [])
                    tool_names = [t.get("name", "") for t in tools]
                    logger.info(f"MCP server '{name}' connected with {len(tools)} tools: {tool_names}")
        except Exception as e:
            logger.warning(f"Failed to check MCP status: {e}")

    def _capture_subprocess_pid(self) -> None:
        """Capture the PID of the underlying claude subprocess for reliable cleanup.

        The SDK nulls its _transport reference during disconnect(), which makes
        it impossible to reach the subprocess later. Capturing the PID upfront
        gives us a reliable fallback for force-killing stray processes.
        """
        try:
            transport = getattr(self.client, '_transport', None)
            process = getattr(transport, '_process', None) if transport else None
            if process and hasattr(process, 'pid'):
                self._subprocess_pid = process.pid
                logger.info(f"Captured claude subprocess PID: {self._subprocess_pid}")
        except Exception:
            pass

    def _force_kill_subprocess(self) -> None:
        """Force-kill the claude subprocess tree by PID.

        This is a last-resort fallback when the SDK's disconnect() chain
        fails to terminate the process (e.g., query.close() raises before
        reaching transport.close()).
        """
        pid = self._subprocess_pid
        if not pid:
            return

        # Check if still alive
        try:
            os.kill(pid, 0)
        except OSError:
            return  # Already dead — nothing to do

        logger.warning(f"Claude subprocess PID {pid} still alive after disconnect, force-killing")

        # Kill child processes first (MCP node processes, subagents, etc.)
        try:
            _subprocess.run(
                ["pkill", "-KILL", "-P", str(pid)],
                capture_output=True, timeout=3,
            )
        except Exception:
            pass

        # Kill the main claude process
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass

    async def cancel(self) -> None:
        """Cancel the running agent."""
        self._cancelled = True

        # Disconnect the client FIRST to terminate the subprocess,
        # before cancelling the receive loop task.
        # This ensures the subprocess is killed even if task cancellation
        # interferes with cleanup in the finally block.
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.client = None

        # Fallback: force-kill by PID if the SDK's disconnect chain
        # failed to terminate the subprocess (e.g., query.close() errored
        # before reaching transport.close()).
        self._force_kill_subprocess()

        # Then cancel the receive loop task
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    async def disconnect(self) -> None:
        """Clean disconnect."""
        if self.client:
            await self.client.disconnect()
        self._force_kill_subprocess()
