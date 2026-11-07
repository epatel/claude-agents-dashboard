import asyncio
import importlib
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
from .profiles import (
    is_tiiny_model,
    profile_options_kwargs,
    redact_env,
    resolve_profile,
    sdk_model_id,
    tiiny_error_hint,
)

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

    groups, ungrouped = _group_annotation_attachments(attachments)
    lines = []

    # Render grouped annotation pairs
    for group in groups.values():
        if "original" in group and "annotated" in group:
            lines += _annotation_pair_lines(group)
            continue
        # Unpaired — treat as simple attachment
        dest = group.get("original") or group.get("annotated")
        if dest:
            ungrouped.append({"dest": dest})

    # Render ungrouped / plain attachments
    if ungrouped:
        if lines:
            lines.append("")
        lines.append("Attached reference images (use Read tool to view):")
        lines += [f"- {att['dest']}" for att in ungrouped]

    if lines:
        lines += ["", _STUDY_ATTACHMENTS_NOTE]
    return "\n".join(lines)


_STUDY_ATTACHMENTS_NOTE = (
    "IMPORTANT: Before making any changes, study the attached images carefully. "
    "Describe what you see and what the annotations are highlighting. "
    "If anything is unclear, use ask_user to confirm your understanding."
)


def _group_annotation_attachments(attachments: list[dict]) -> tuple[dict[str, dict], list[dict]]:
    """Split attachments into annotation groups and plain ones.

    Groups are keyed by annotation timestamp prefix:
    prefix -> {"original": dest, "annotated": dest, "summary": text}.
    """
    groups: dict[str, dict] = {}
    ungrouped: list[dict] = []
    for att in attachments:
        m = _ANNOTATION_PREFIX_RE.match(att["filename"])
        if not m:
            ungrouped.append(att)
            continue
        group = groups.setdefault(m.group(1), {})
        group[m.group(2)] = att["dest"]
        if att.get("annotation_summary"):
            group["summary"] = att["annotation_summary"]
    return groups, ungrouped


def _annotation_pair_lines(group: dict) -> list[str]:
    """Prompt lines for an original + annotated screenshot pair."""
    lines = [
        "The following annotated screenshot is attached:",
        f"- {group['original']} (clean screenshot without annotations)",
        f"- {group['annotated']} (same screenshot with annotation markers drawn on it)",
    ]
    if "summary" in group:
        lines.append(f"- Annotations: {group['summary']}")
    return lines



# --- Fixed system-prompt sections (appended in _build_system_prompt) -----------

_PEEK_NOTE = (
    "\n\nOTHER AGENTS ARE WORKING IN PARALLEL, each in its own git worktree "
    "forked from the same base. You cannot read their files directly, but "
    "mcp__peek_worktree__peek_worktree shows you what they have changed so "
    "far: call it with no arguments for every active worktree (files that "
    "collide with yours are flagged), with item_id for one agent's full file "
    "list, and with item_id + path for that agent's diff of a single file. "
    "Peek BEFORE you start editing a file that is likely shared (config, "
    "router, schema, shared module) and again before you finish. If another "
    "agent is already changing a file you need, match their direction, keep "
    "your edit narrow, or ask the user via mcp__clarification__ask_user — a "
    "merge conflict found now is far cheaper than one found at merge time."
)

_CLARIFY_NOTE = (
    "\n\nIMPORTANT: If you need to ask the user a question or need clarification, "
    "you MUST use the ask_user MCP tool (mcp__clarification__ask_user). "
    "Do NOT use ToolSearch, AskUserQuestion, or any other built-in tool to ask questions. "
    "The ask_user tool is the ONLY way to communicate with the user."
)

_COMMIT_NOTE = (
    "\n\nIMPORTANT: When you have finished your task, you MUST call the "
    "set_commit_message tool with a concise commit message summarizing what you did. "
    "Use conventional style: start with a verb (Add, Fix, Update, Refactor, Remove). "
    "This is required — do not skip it."
)

# Task lifecycle: weak/local models otherwise invent a manual "close the
# card" procedure (TaskUpdate/TaskStop/inloop, or spawning child todos to
# mark their own work done) and burn the whole budget flailing. Completion
# is automatic — they just need to stop.
_LIFECYCLE_NOTE = (
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

# Extra push for profiles with lifecycle_addendum (weak local models).
_LIFECYCLE_ADDENDUM = (
    "\n\nTO FINISH THIS TASK: stop calling tools. Write one short final message, call "
    "set_commit_message once, and end your turn. Do nothing else. The card moves to Done "
    "by itself. Never spawn another todo to finish or verify your own work."
    "\n\nBE DECISIVE: For a simple factual query, run ONE command to get the answer and "
    "then proceed. Trust the output you see — do not re-run the same command in different "
    "ways or exhaust every interpretation. State your assumptions clearly instead of "
    "verifying them repeatedly."
)

_TODO_NOTE = (
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

_COMMAND_NOTE = (
    "\n\nIf a shell command is blocked, use the request_command_access tool "
    "to ask the user for permission. Provide the command name and reason."
)

_TOOL_NOTE = (
    "\n\nIf a built-in tool (like WebSearch or WebFetch) is blocked, use the "
    "mcp__tool_access__request_tool_access tool to ask the user for permission. "
    "Do NOT use ToolSearch to find it — call it directly."
)

_BRAINSTORM_NOTE = (
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

_DEBUG_NOTE = (
    "\n\nIMPORTANT: If the task is about fixing a bug, debugging, or troubleshooting — "
    "do NOT guess at fixes. Investigate first:\n"
    "1. Read the full error message/stack trace\n"
    "2. Reproduce the issue and trace the data flow to find root cause\n"
    "3. Find similar working code and compare\n"
    "4. Form a specific hypothesis, test with the smallest possible change\n"
    "5. If stuck after 3 attempts, use mcp__clarification__ask_user to explain what you tried"
)

_BROWSER_NOTE = (
    "\n\nYou have access to a web browser via the Claude-in-Chrome tools "
    "(mcp__claude-in-chrome__*): navigate to URLs, read page content, inspect "
    "the DOM, take screenshots, fill forms, and read the console/network. Use "
    "them whenever the task involves the web, a running UI, or anything you need "
    "to see in a browser. The browser shares the user's Chrome session — be "
    "careful with any destructive or authenticated actions."
)

_GRAPH_NOTE = (
    "\n\nThis project has a knowledge graph of its code. Before editing "
    "unfamiliar code, use mcp__graph_query__graph_query to orient — ask what "
    "calls a function, where a concept lives, or how a flow connects. "
    "Answers cite source locations you can open."
)


# Board MCP servers: (server name, enabling callback attr, module, factory).
# Order matters — it is the order servers are registered.
_BOARD_SERVERS = (
    ("clarification", "on_clarify", "clarification", "create_clarification_server"),
    ("todo", "on_create_todo", "todo", "create_todo_server"),
    ("commit_message", "on_set_commit_message", "commit_message", "create_commit_message_server"),
    ("command_access", "on_request_command", "command_access", "create_command_access_server"),
    ("tool_access", "on_request_tool", "tool_access", "create_tool_access_server"),
    ("board_view", "on_view_board", "board_view", "create_board_view_server"),
    ("who_am_i", "on_who_am_i", "who_am_i", "create_who_am_i_server"),
    ("peek_worktree", "on_peek_worktree", "peek_worktree", "create_peek_worktree_server"),
    ("shortcut", "on_create_shortcut", "shortcut", "create_shortcut_server"),
)

# Tools each built-in server exposes, in whitelist order. Any other server in
# mcp_servers is external and allowed by wildcard / prefix instead.
_BUILTIN_SERVER_TOOLS = {
    "clarification": ["mcp__clarification__ask_user"],
    "todo": ["mcp__todo__create_todo", "mcp__todo__delete_todo", "mcp__todo__create_epic"],
    "commit_message": ["mcp__commit_message__set_commit_message"],
    "command_access": ["mcp__command_access__request_command_access"],
    "tool_access": ["mcp__tool_access__request_tool_access"],
    "board_view": ["mcp__board_view__view_board"],
    "who_am_i": ["mcp__who_am_i__who_am_i"],
    "peek_worktree": ["mcp__peek_worktree__peek_worktree"],
    "shortcut": ["mcp__shortcut__create_shortcut"],
    "graph_query": ["mcp__graph_query__graph_query"],
}


def _token_usage(usage: dict) -> tuple:
    """(input, output, total) tokens from a ResultMessage usage dict.

    Accepts both *_tokens and *_token_count keys; derives the total when only
    the components are given.
    """
    input_tokens = usage.get("input_tokens") or usage.get("input_token_count")
    output_tokens = usage.get("output_tokens") or usage.get("output_token_count")
    total_tokens = usage.get("total_tokens") or usage.get("total_token_count")
    has_components = None not in (input_tokens, output_tokens)
    if total_tokens is None and has_components:
        total_tokens = input_tokens + output_tokens
    return input_tokens, output_tokens, total_tokens


def _builtin_tool_names(mcp_servers: dict) -> list[str]:
    """Whitelist entries for the built-in servers present, in table order."""
    names: list[str] = []
    for server_name, tools in _BUILTIN_SERVER_TOOLS.items():
        if server_name in mcp_servers:
            names.extend(tools)
    return names


def _external_server_names(mcp_servers: dict) -> list[str]:
    """Servers in ``mcp_servers`` that are not one of the dashboard's built-ins."""
    return [name for name in mcp_servers if name not in _BUILTIN_SERVER_TOOLS]


async def _notify(callback, *args) -> None:
    """Await ``callback(*args)`` if a callback is set."""
    if callback:
        await callback(*args)


class ClaudeAgentSession(AbstractAgentSession):
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
        on_peek_worktree=None,
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
        local_env: dict[str, str] | None = None,
        load_claude_md: bool = False,
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
        self.local_env = local_env
        # When True, inject the worktree CLAUDE.md into a local-provider system
        # prompt (the local path uses setting_sources=["local"], which does not
        # auto-load it the way the Claude path's ["project"] does).
        self.load_claude_md = load_claude_md
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
        self.on_peek_worktree = on_peek_worktree    # async callback(item_id, path) -> str (other agents' worktrees)
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
        # Provider profile: which SDK options and features this run gets.
        # The local profile disables heavy features (graphify, external MCP,
        # plugins, chrome) whose tool definitions overwhelm small local models.
        profile = resolve_profile(self.local_env, model=self.model, load_claude_md=self.load_claude_md)
        mcp_servers = self._build_mcp_servers(profile)
        # Chrome browser integration is launched via the `claude --chrome` flag
        # below. Skipped for local models — the extra browser tool definitions
        # overwhelm them.
        chrome_enabled = self.use_chrome and profile.chrome
        full_system_prompt = self._build_system_prompt(mcp_servers, profile, chrome_enabled)
        allowed_tools = self._build_allowed_tools(mcp_servers, chrome_enabled)
        plugins, plugin_prefixes = self._build_plugins(profile)
        hooks = self._build_hooks()

        # External MCP servers, plugins and the CLI-registered Chrome server are
        # allowed by prefix in can_use_tool — SDK wildcard patterns don't work.
        external_mcp_prefixes = [f"mcp__{name}__" for name in _external_server_names(mcp_servers)]
        chrome_prefixes = ["mcp__claude-in-chrome__"] if chrome_enabled else []
        can_use_tool_fn = self._build_can_use_tool(
            allowed_tools, plugin_prefixes + external_mcp_prefixes + chrome_prefixes
        )

        # Provider-divergent SDK options (permission_mode, thinking,
        # setting_sources, env, stderr) come from the profile — the Ollama
        # rationale (thinking disabled, no `user` settings) is documented in
        # profiles.resolve_profile and locked in project-plan.md Decisions.
        if profile.local:
            logger.info(f"{profile.name} mode: using lightweight SDK options for model {self.model}")
            # redact_env: a Tiiny env carries the API key.
            logger.info(f"{profile.name} env: {redact_env(self.local_env)}")

        options_kwargs = dict(
            cwd=self.worktree_path,
            system_prompt=full_system_prompt,
            # Tiiny ids are namespaced ("tiiny/default"); the SDK gets the bare id.
            model=sdk_model_id(self.model),
            mcp_servers=mcp_servers if mcp_servers else None,
            allowed_tools=allowed_tools if allowed_tools else None,
            can_use_tool=can_use_tool_fn,
            add_dirs=[str(self.worktree_path), *(str(p) for p in self.sibling_repo_paths)],
            plugins=plugins if plugins else None,
            hooks=hooks,
            # The prompt is assembled from the board item's own title and
            # description. Without this, the CLI would expand any `@path` in
            # that text into a file read and dispatch a leading `/name` as a
            # slash command — interpreting text that was only ever meant to be
            # instructions. Nothing in the dashboard builds `@path` references
            # (attachments are listed as plain paths for the Read tool), so
            # passing prompts through verbatim costs us nothing.
            verbatim_prompts=True,
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
            attachment_prompt = build_attachment_prompt(self._stage_attachments(attachments))
            if attachment_prompt:
                prompt += "\n\n" + attachment_prompt

        await self.client.query(prompt)

    # -- start() building blocks ---------------------------------------------

    def _build_mcp_servers(self, profile) -> dict:
        """The board tools this session's callbacks enable, plus profile-gated extras."""
        mcp_servers = self._board_mcp_servers()

        # graphify graph_query tool — only when enabled in config
        graph_wanted = bool(self.on_graph_query) and self.graphify_enabled
        if graph_wanted and profile.graphify:
            from .graph_query import create_graph_query_server
            mcp_servers["graph_query"] = create_graph_query_server(self.on_graph_query)

        # External MCP servers from agent configuration (database)
        external_configured = bool(self.mcp_enabled) and bool(self.mcp_servers)
        if not external_configured:
            return mcp_servers
        if not profile.external_mcp:
            logger.info(f"{profile.name} mode: skipping external MCP servers to reduce context size")
            return mcp_servers
        external = self._external_mcp_servers()
        if external:
            mcp_servers.update(external)
            logger.info(f"Loaded {len(external)} MCP servers from agent configuration")
        return mcp_servers

    def _board_mcp_servers(self) -> dict:
        """One in-process MCP server per board callback this session was given."""
        mcp_servers = {}
        for name, attr, module, factory in _BOARD_SERVERS:
            callback = getattr(self, attr)
            if not callback:
                continue
            create = getattr(importlib.import_module(f".{module}", __package__), factory)
            # The todo server also carries delete_todo and create_epic.
            extra = (self.on_delete_todo, self.on_create_epic) if name == "todo" else ()
            mcp_servers[name] = create(callback, *extra)
        return mcp_servers

    def _external_mcp_servers(self) -> dict:
        """The configured external MCP servers as a dict ({} if unusable).

        mcp_servers arrives as a parsed dict; a JSON string is tolerated for
        legacy callers.
        """
        servers = self.mcp_servers
        if isinstance(servers, str):
            try:
                servers = json.loads(servers)
            except Exception as e:
                logger.warning(f"Failed to parse MCP servers from agent config: {e}")
                return {}
        return servers if isinstance(servers, dict) else {}

    def _build_system_prompt(self, mcp_servers: dict, profile, chrome_enabled: bool) -> str:
        """The base system prompt plus every note that applies to this session."""
        lifecycle_note = _LIFECYCLE_NOTE + (_LIFECYCLE_ADDENDUM if profile.lifecycle_addendum else "")
        shared_plan_note, epic_plan_note = self._plan_notes()
        return "".join([
            self.system_prompt or "",
            self._cwd_note(),
            self._board_item_note(),
            _PEEK_NOTE if "peek_worktree" in mcp_servers else "",
            self._multi_repo_note(),
            shared_plan_note,
            epic_plan_note,
            _CLARIFY_NOTE,
            _COMMIT_NOTE,
            lifecycle_note,
            _TODO_NOTE,
            _BRAINSTORM_NOTE,
            _DEBUG_NOTE,
            _COMMAND_NOTE,
            _TOOL_NOTE,
            _BROWSER_NOTE if chrome_enabled else "",
            _GRAPH_NOTE if "graph_query" in mcp_servers else "",
            self._claude_md_note(profile),
        ])

    def _cwd_note(self) -> str:
        """Ensure the agent knows to work in the worktree directory."""
        return (
            f"\n\nIMPORTANT: Your working directory is {self.worktree_path}. "
            "All file operations must be within this directory."
            "\n\nThis directory is a git worktree — an isolated copy of the target project. "
            "Your changes here will be merged back to the main branch when your task is done. "
            "Other agents working on other tasks have their own separate worktrees. "
            "Always use relative paths or paths within this worktree — never reference "
            "other worktrees or the main project checkout directly."
        )

    def _board_item_note(self) -> str:
        if not self.item_id:
            return ""
        return (
            f"\n\nYOUR BOARD ITEM: you are working on board item `{self.item_id}`. "
            "Call the who_am_i tool (mcp__who_am_i__who_am_i) any time for your full "
            "item details (title, column, dependencies). Use this ID when a follow-up "
            "task must wait for you — pass it in the `requires` field of create_todo. "
            "You never need to guess which card is yours from view_board."
        )

    def _multi_repo_note(self) -> str:
        """Multi-repo preamble: sibling repos as read-only refs, plus the
        parent-workspace CLAUDE.md / AGENTS.md contents."""
        if not (self.workspace_root and self.sibling_repo_paths):
            return ""
        repo_lines = "\n".join(f"- {p}" for p in self.sibling_repo_paths)
        note = (
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
                    note += f"\n\n--- Workspace {fname} ({fpath}) ---\n{content}"
            except Exception as e:
                logger.warning(f"Could not read workspace {fname} at {fpath}: {e}")
        return note

    def _plan_notes(self) -> tuple[str, str]:
        """Notes pointing at the shared project plan and the item's epic plan.

        A fanned-out multi-agent build keeps one source of truth
        (project-plan.md at the repo / workspace root); rather than make every
        task description repeat "read the plan first, update it before
        finishing", surface that convention for any agent whose checkout
        carries the file. The epic plan is the item's own workstream plan.
        """
        shared_plan_note = ""
        plan_path = self._find_plan_file("project-plan.md", "shared plan")
        if plan_path:
            shared_plan_note = (
                f"\n\nSHARED PROJECT PLAN: this project has a shared plan at "
                f"{plan_path}. READ IT FIRST to understand the goal, milestones, "
                "decisions, and current state before you start. BEFORE you finish, "
                "update its 'Current state' and 'Decisions' sections to reflect what "
                "you did. It is the single source of truth shared across every task — "
                "keep it accurate so the next agent picks up where you left off."
            )
        epic_plan_note = ""
        epic_plan_path = (
            self._find_plan_file(self.epic_plan_relpath, "epic plan") if self.epic_plan_relpath else None
        )
        if epic_plan_path:
            epic_plan_note = (
                f"\n\nEPIC PLAN: your task belongs to an epic whose shared plan "
                f"is at {epic_plan_path}. This is the detailed plan for your "
                "workstream — read it first and update its 'Current state' and "
                "'Decisions' before you finish, alongside the project-wide plan."
            )
        return shared_plan_note, epic_plan_note

    def _find_plan_file(self, relpath: str, label: str) -> Path | None:
        """First existing ``relpath`` under the worktree, then the workspace root."""
        plan_roots = [self.worktree_path]
        if self.workspace_root:
            plan_roots.append(self.workspace_root)
        for plan_root in plan_roots:
            try:
                path = plan_root / relpath
                if path.is_file():
                    return path
            except Exception as e:
                logger.warning(f"Could not check for {label} at {plan_root}: {e}")
        return None

    def _claude_md_note(self, profile) -> str:
        """The worktree CLAUDE.md, for profiles that opt in to injecting it.

        Local agents run with setting_sources=["local"], which does NOT
        auto-load the project CLAUDE.md (the Claude path's ["project"] does).
        With the "Load project CLAUDE.md" toggle on, inject it into the system
        prompt so project conventions reach the local model.
        """
        if not profile.inject_claude_md:
            return ""
        claude_md_path = self.worktree_path / "CLAUDE.md"
        try:
            if claude_md_path.is_file():
                content = claude_md_path.read_text(errors="replace")
                logger.info(f"{profile.name} mode: injected project CLAUDE.md into system prompt")
                return f"\n\n--- Project CLAUDE.md ({claude_md_path}) ---\n{content}"
            logger.info(f"{profile.name} 'Load project CLAUDE.md' is on but no CLAUDE.md found in worktree")
        except Exception as e:
            logger.warning(f"Could not read project CLAUDE.md at {claude_md_path}: {e}")
        return ""

    def _build_allowed_tools(self, mcp_servers: dict, chrome_enabled: bool) -> list[str]:
        """The tool whitelist: board tools, external MCP wildcards, chrome, Bash, optional built-ins."""
        allowed_tools = _builtin_tool_names(mcp_servers)

        # Allow all tools from external MCP servers (using wildcard for each server)
        external = _external_server_names(mcp_servers)
        for server_name in external:
            logger.info(f"Allowing all tools from external MCP server: {server_name}")
        allowed_tools += [f"mcp__{server_name}__*" for server_name in external]

        # The `claude --chrome` flag registers the Claude-in-Chrome MCP server
        # at the CLI level, so it never appears in `mcp_servers`.
        if chrome_enabled:
            allowed_tools.append("mcp__claude-in-chrome__*")
            logger.info("Chrome integration enabled: allowing mcp__claude-in-chrome__* tools")

        # Always allow Bash in the tool whitelist — permission_mode and the
        # PreToolUse hook handle actual command filtering.
        allowed_tools.append("Bash")

        # Always add optional built-in tools to the whitelist — the PreToolUse
        # hook filters disabled ones and directs the agent to request access.
        from .tool_filter import OPTIONAL_TOOL_NAMES
        allowed_tools += [name for name in OPTIONAL_TOOL_NAMES if name not in allowed_tools]
        return allowed_tools

    def _build_plugins(self, profile) -> tuple[list[dict] | None, list[str]]:
        """Plugin configs for the SDK and their MCP tool prefixes.

        Skipped for local models — plugins add many tool definitions that
        overwhelm them.
        """
        if not self.plugins:
            return None, []
        if not profile.plugins:
            logger.info(f"{profile.name} mode: skipping plugins to reduce context size")
            return None, []
        plugins, plugin_prefixes = [], []
        for plugin_config in self.plugins:
            plugin_path = plugin_config.get("path", "")
            if plugin_path:
                plugins.append({"type": "local", "path": plugin_path})
                plugin_prefixes.append(f"mcp__plugin_{Path(plugin_path).name}")
                logger.info(f"Loading plugin from: {plugin_path}")
        return plugins, plugin_prefixes

    def _build_hooks(self) -> dict | None:
        """PreToolUse hooks: bash command filter, optional-tool filter, path guard."""
        hook_matchers = []

        if not self.bash_yolo and self.allowed_commands:
            from .command_filter import make_command_filter_hook
            hook_matchers.append(
                HookMatcher(
                    matcher="Bash",
                    hooks=[make_command_filter_hook(self.allowed_commands, session=self)],
                )
            )

        # Tool filter hook for optional built-in tools
        from .tool_filter import OPTIONAL_TOOL_NAMES, make_tool_filter_hook
        for tool_name in OPTIONAL_TOOL_NAMES:
            hook_matchers.append(
                HookMatcher(matcher=tool_name, hooks=[make_tool_filter_hook(self.allowed_builtin_tools)])
            )

        # Path guard hook to prevent agents from editing main repo.
        # In multi-repo mode, workspace_root unlocks reads to sibling repos.
        from .path_guard import make_path_guard_hook
        path_guard_hook = make_path_guard_hook(self.worktree_path, workspace_root=self.workspace_root)
        for guarded_tool in ['Read', 'Edit', 'Write', 'Glob', 'Grep', 'Bash']:
            hook_matchers.append(HookMatcher(matcher=guarded_tool, hooks=[path_guard_hook]))

        return {"PreToolUse": hook_matchers} if hook_matchers else None

    @staticmethod
    def _build_can_use_tool(allowed_tools: list[str], prefixes: list[str]):
        """can_use_tool callback allowing whitelisted tools and the given MCP prefixes.

        None when there are no prefixes — the whitelist alone then applies.
        """
        if not prefixes:
            return None
        allowed_set = set(allowed_tools) if allowed_tools else set()

        async def can_use_tool(tool_name: str, *args):
            if tool_name in allowed_set:
                return PermissionResultAllow()
            if any(tool_name.startswith(prefix) for prefix in prefixes):
                return PermissionResultAllow()
            # Allow standard (non-MCP) tools — permission_mode handles them
            if not tool_name.startswith("mcp__"):
                return PermissionResultAllow()
            return PermissionResultDeny()
        return can_use_tool

    def _stage_attachments(self, attachments: list[dict]) -> list[dict]:
        """Copy attachments into the worktree's gitignored .agent-attachments/ dir.

        Returns the ones copied, as {filename, dest, annotation_summary}.
        """
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
        return processed

    # -- message loop ----------------------------------------------------------

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
                        await self._handle_content_block(block)
                elif isinstance(message, ResultMessage):
                    await self._handle_result(message)
                    return
                elif isinstance(message, SystemMessage):
                    await self._handle_system_message(message)
        except Exception as e:
            logger.exception("Agent session error")
            await _notify(self.on_error, str(e))
        finally:
            await self._close_client(client_ref)

    async def _handle_system_message(self, message) -> None:
        """Log system messages (progress, etc.) to the work log."""
        if not (self.on_message and hasattr(message, 'content')):
            return
        text = str(message.content) if message.content else ""
        if text:
            await self.on_message(f"[system] {text}")

    async def _close_client(self, client_ref) -> None:
        """Disconnect the SDK client and make sure its subprocess is gone.

        Uses the reference captured at loop start, since cancel() may already
        have set self.client to None.
        """
        self.client = None
        if client_ref:
            try:
                await client_ref.disconnect()
            except Exception:
                pass
        # Last-resort: force-kill by saved PID if process somehow survived
        self._force_kill_subprocess()

    async def _handle_content_block(self, block) -> None:
        """Forward one assistant content block to the matching callback."""
        if isinstance(block, TextBlock):
            await _notify(self.on_message, block.text)
        elif isinstance(block, ThinkingBlock):
            if block.thinking:
                await _notify(self.on_thinking, block.thinking)
        elif isinstance(block, (ToolUseBlock, ServerToolUseBlock)):
            # ServerToolUseBlock: a server-executed tool call (advisor,
            # web_search) — surfaced like any tool use.
            await _notify(self.on_tool_use, block.name, block.input)
        elif isinstance(block, ServerToolResultBlock):
            # Result of a server-executed tool (e.g. advisor analysis). Dropping
            # it made messages carrying only server-side calls arrive empty.
            text = _server_result_text(block.content) if self.on_message else ""
            if text:
                await self.on_message(f"[advisor] {text}")

    async def _handle_result(self, message) -> None:
        """Record the session id and report the run's outcome via on_complete."""
        if message.session_id:
            self.current_session_id = message.session_id

        input_tokens, output_tokens, total_tokens = _token_usage(message.usage or {})
        # HTTP status of a failing API call (429/500/529, etc.). Lets callers
        # distinguish transient API errors from agent or task failures.
        api_error_status = getattr(message, "api_error_status", None)
        if not isinstance(api_error_status, int):
            api_error_status = None

        result = AgentResult(
            success=not message.is_error,
            session_id=message.session_id,
            cost_usd=message.total_cost_usd,
            error=self._error_text(message, api_error_status),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            api_error_status=api_error_status,
        )
        if self.on_complete:
            await self.on_complete(result)

    def _error_text(self, message, api_error_status: int | None) -> str | None:
        """The error for a failed result, prefixed with its HTTP status and any Tiiny hint."""
        if not message.is_error:
            return None
        error_text = message.result
        if api_error_status:
            error_text = f"[HTTP {api_error_status}] {error_text or ''}".strip()
        if is_tiiny_model(self.model):
            hint = tiiny_error_hint(api_error_status, error_text)
            if hint:
                error_text = f"{error_text or ''} — {hint}".strip(" —")
        return error_text

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


# Backwards-compat alias — prefer ClaudeAgentSession. Remove when the second
# runtime (KimiAgentSession) lands and all callers are provider-aware.
AgentSession = ClaudeAgentSession
