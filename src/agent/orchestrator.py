import asyncio
import json
import logging
from pathlib import Path

from ..database import Database
from ..web.websocket import ConnectionManager
from ..git.worktree import create_worktree, remove_worktree, cleanup_worktree
from ..git.operations import get_main_branch, merge_branch
from .session import AgentSession, AgentResult
from ..models import new_id

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    """Manages running agent instances, one per active item."""

    def __init__(
        self,
        target_project: Path,
        data_dir: Path,
        db: Database,
        ws_manager: ConnectionManager,
    ):
        self.target_project = target_project
        self.data_dir = data_dir
        self.worktree_dir = data_dir / "worktrees"
        self.worktree_dir.mkdir(exist_ok=True)
        self.db = db
        self.ws_manager = ws_manager
        self.sessions: dict[str, AgentSession] = {}
        self._clarify_events: dict[str, asyncio.Event] = {}
        self._clarify_responses: dict[str, str] = {}

    async def _on_clarify(self, item_id: str, prompt: str, choices: list[str] | None) -> str:
        """Called when agent uses ask_user tool. Blocks until user responds."""
        # Move item to clarify
        await self._update_item(item_id, column_name="clarify", status=None)
        await self._log(item_id, "system", f"Agent needs clarification: {prompt}")

        # Store clarification in DB
        import json as _json
        async with self.db.connect() as conn:
            await conn.execute(
                "INSERT INTO clarifications (item_id, prompt, choices) VALUES (?, ?, ?)",
                (item_id, prompt, _json.dumps(choices) if choices else None),
            )
            await conn.commit()

        # Broadcast to frontend
        await self.ws_manager.broadcast("clarification_requested", {
            "item_id": item_id,
            "prompt": prompt,
            "choices": _json.dumps(choices) if choices else None,
        })

        # Wait for user response
        event = asyncio.Event()
        self._clarify_events[item_id] = event
        await event.wait()

        response = self._clarify_responses.pop(item_id, "")
        self._clarify_events.pop(item_id, None)

        # Move back to doing
        await self._update_item(item_id, column_name="doing", status="running")
        await self._log(item_id, "system", f"User responded: {response}")

        return response

    async def _on_create_todo(self, item_id: str, title: str, description: str) -> dict:
        """Called when agent uses create_todo tool. Creates a new todo item."""
        todo_id = new_id()

        # Get next position in todo column
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM items WHERE column_name = 'todo'"
            )
            row = await cursor.fetchone()
            position = row[0] if row else 0

            # Create new todo item
            await conn.execute(
                "INSERT INTO items (id, title, description, column_name, position) VALUES (?, ?, ?, 'todo', ?)",
                (todo_id, title, description, position),
            )
            await conn.commit()

            # Get the created item
            cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (todo_id,))
            item = dict(await cursor.fetchone())

        # Log the creation
        await self._log(item_id, "system", f"Created todo item: {title}")

        # Broadcast to frontend
        await self.ws_manager.broadcast("item_created", item)

        return item

    def _format_tool_use(self, name: str, inp: dict) -> str:
        """Format tool use for readable work log display."""
        if name == "Write":
            path = inp.get("file_path", "")
            return f"**Write** `{path}`"
        elif name == "Edit":
            path = inp.get("file_path", "")
            return f"**Edit** `{path}`"
        elif name == "Read":
            path = inp.get("file_path", "")
            return f"**Read** `{path}`"
        elif name == "Bash":
            cmd = inp.get("command", "")
            if len(cmd) > 120:
                cmd = cmd[:120] + "..."
            return f"**Bash** `{cmd}`"
        elif name == "Glob":
            return f"**Glob** `{inp.get('pattern', '')}`"
        elif name == "Grep":
            return f"**Grep** `{inp.get('pattern', '')}` in `{inp.get('path', '.')}`"
        elif name == "create_todo":
            title = inp.get("title", "")
            return f"**Create Todo** {title}"
        elif name == "ask_user":
            question = inp.get("question", "")
            if len(question) > 100:
                question = question[:100] + "..."
            return f"**Ask User** {question}"
        else:
            summary = str(inp)
            if len(summary) > 100:
                summary = summary[:100] + "..."
            return f"**{name}** {summary}"

    async def _get_agent_config(self) -> dict:
        async with self.db.connect() as conn:
            cursor = await conn.execute("SELECT * FROM agent_config WHERE id = 1")
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return {}

    async def _log(self, item_id: str, entry_type: str, content: str, metadata: str | None = None):
        async with self.db.connect() as conn:
            await conn.execute(
                "INSERT INTO work_log (item_id, entry_type, content, metadata) VALUES (?, ?, ?, ?)",
                (item_id, entry_type, content, metadata),
            )
            await conn.commit()
        await self.ws_manager.broadcast("agent_log", {
            "item_id": item_id,
            "entry_type": entry_type,
            "content": content,
        })

    async def _update_item(self, item_id: str, **kwargs):
        async with self.db.connect() as conn:
            sets = ", ".join(f"{k} = ?" for k in kwargs)
            vals = list(kwargs.values()) + [item_id]
            await conn.execute(
                f"UPDATE items SET {sets}, updated_at = datetime('now') WHERE id = ?",
                vals,
            )
            await conn.commit()
            cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
            item = dict(await cursor.fetchone())
        await self.ws_manager.broadcast("item_updated", item)
        return item

    async def start_agent(self, item_id: str) -> dict:
        """Start an agent for an item. Creates worktree, launches agent."""
        # Get item
        async with self.db.connect() as conn:
            cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
            item = dict(await cursor.fetchone())

        config = await self._get_agent_config()
        branch_name = f"agent/{item_id}"

        # Reuse existing worktree if it exists, otherwise create new
        worktree_path = self.worktree_dir / branch_name.replace("/", "-")
        if item.get("worktree_path") and Path(item["worktree_path"]).exists():
            worktree_path = Path(item["worktree_path"])
        elif worktree_path.exists():
            pass  # Worktree dir exists from a previous run
        else:
            # Clean up stale branch if it exists
            try:
                from ..git.operations import run_git
                await run_git(self.target_project, "branch", "-D", branch_name)
            except Exception:
                pass
            worktree_path = await create_worktree(
                self.target_project, self.worktree_dir, branch_name
            )

        # Update item state
        item = await self._update_item(
            item_id,
            column_name="doing",
            status="running",
            branch_name=branch_name,
            worktree_path=str(worktree_path),
        )

        await self._log(item_id, "system", "Agent started")

        # Build system prompt
        system_prompt = config.get("system_prompt", "") or ""
        project_context = config.get("project_context", "") or ""
        if project_context:
            system_prompt = f"{system_prompt}\n\nProject context:\n{project_context}"

        # Create session with callbacks
        session = AgentSession(
            worktree_path=worktree_path,
            system_prompt=system_prompt,
            model=config.get("model"),
            on_message=lambda text, iid=item_id: self._log(iid, "agent_message", text),
            on_tool_use=lambda name, inp, iid=item_id: self._log(
                iid, "tool_use", self._format_tool_use(name, inp), json.dumps(inp)
            ),
            on_thinking=lambda text, iid=item_id: self._log(iid, "thinking", text),
            on_complete=lambda result, iid=item_id: self._on_agent_complete(iid, result),
            on_error=lambda err, iid=item_id: self._on_agent_error(iid, err),
            on_clarify=lambda prompt, choices, iid=item_id: self._on_clarify(iid, prompt, choices),
            on_create_todo=lambda title, desc, iid=item_id: self._on_create_todo(iid, title, desc),
        )

        self.sessions[item_id] = session

        # Build the prompt from item description
        prompt = f"Task: {item['title']}\n\n{item['description']}"

        # Launch agent in background so HTTP response returns immediately
        asyncio.create_task(self._run_agent(item_id, session, prompt))

        return item

    async def _run_agent(self, item_id: str, session: AgentSession, prompt: str, resume_session_id: str | None = None):
        """Run agent session in background."""
        try:
            await session.start(prompt, resume_session_id=resume_session_id)
        except Exception as e:
            logger.exception(f"Agent failed to start for {item_id}")
            await self._on_agent_error(item_id, str(e))

    async def _on_agent_complete(self, item_id: str, result: AgentResult):
        """Called when agent finishes."""
        self.sessions.pop(item_id, None)

        if result.success:
            await self._log(item_id, "system",
                           f"Agent completed (cost: ${result.cost_usd:.4f})" if result.cost_usd else "Agent completed")
            await self._update_item(
                item_id,
                column_name="review",
                status=None,
                session_id=result.session_id,
            )
        else:
            await self._log(item_id, "error", f"Agent failed: {result.error}")
            await self._update_item(item_id, status="failed")

    async def _on_agent_error(self, item_id: str, error: str):
        """Called when agent crashes."""
        self.sessions.pop(item_id, None)
        await self._log(item_id, "error", f"Agent error: {error}")
        await self._update_item(item_id, status="failed")

    async def cancel_agent(self, item_id: str) -> dict:
        """Cancel a running agent."""
        session = self.sessions.pop(item_id, None)
        if session:
            await session.cancel()

        await self._log(item_id, "system", "Agent cancelled by user")
        return await self._update_item(
            item_id,
            column_name="todo",
            status="cancelled",
        )

    async def retry_agent(self, item_id: str) -> dict:
        """Retry a failed agent — restart from scratch in existing worktree."""
        # Cancel any existing session
        session = self.sessions.pop(item_id, None)
        if session:
            await session.cancel()

        async with self.db.connect() as conn:
            cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
            item = dict(await cursor.fetchone())

        # If worktree exists, reuse it; otherwise create new
        worktree_path = Path(item["worktree_path"]) if item.get("worktree_path") else None
        if not worktree_path or not worktree_path.exists():
            branch_name = item.get("branch_name") or f"agent/{item_id}"
            worktree_path = await create_worktree(
                self.target_project, self.worktree_dir, branch_name
            )
            await self._update_item(
                item_id,
                branch_name=branch_name,
                worktree_path=str(worktree_path),
            )

        await self._log(item_id, "system", "Agent retrying")

        # Resume from previous session if possible
        resume_id = item.get("session_id")
        return await self.start_agent(item_id)

    async def approve_item(self, item_id: str) -> dict:
        """Approve a reviewed item — merge into main."""
        async with self.db.connect() as conn:
            cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
            item = dict(await cursor.fetchone())

        branch = item["branch_name"]
        worktree_path = Path(item["worktree_path"]) if item.get("worktree_path") else None
        success, message = await merge_branch(
            self.target_project, branch, worktree_path=worktree_path
        )

        if success:
            await self._log(item_id, "system", f"Merged {branch} into main")

            # Clean up worktree
            worktree_path = Path(item["worktree_path"]) if item.get("worktree_path") else None
            if worktree_path:
                try:
                    await cleanup_worktree(self.target_project, worktree_path, branch)
                except Exception as e:
                    logger.warning(f"Worktree cleanup failed: {e}")

            return await self._update_item(
                item_id,
                column_name="done",
                status=None,
                worktree_path=None,
            )
        else:
            await self._log(item_id, "system", f"Merge conflict: {message}")
            await self._update_item(item_id, status="resolving_conflicts")
            # TODO: spawn merge resolution agent
            return await self._update_item(item_id, status="resolving_conflicts")

    async def request_changes(self, item_id: str, comments: list[str]) -> dict:
        """Send review comments back to the agent."""
        async with self.db.connect() as conn:
            # Store comments
            for comment in comments:
                await conn.execute(
                    "INSERT INTO review_comments (item_id, content) VALUES (?, ?)",
                    (item_id, comment),
                )
            await conn.commit()

            cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
            item = dict(await cursor.fetchone())

        # Build feedback prompt
        feedback = "Review feedback — please address these comments:\n\n"
        feedback += "\n".join(f"- {c}" for c in comments)

        await self._log(item_id, "user_action", f"Review changes requested: {'; '.join(comments)}")

        # Update item to doing
        item = await self._update_item(
            item_id,
            column_name="doing",
            status="running",
        )

        # Start new agent session with feedback
        config = await self._get_agent_config()
        system_prompt = config.get("system_prompt", "") or ""
        worktree_path = Path(item["worktree_path"])

        session = AgentSession(
            worktree_path=worktree_path,
            system_prompt=system_prompt,
            model=config.get("model"),
            on_message=lambda text, iid=item_id: self._log(iid, "agent_message", text),
            on_tool_use=lambda name, inp, iid=item_id: self._log(
                iid, "tool_use", self._format_tool_use(name, inp), json.dumps(inp)
            ),
            on_thinking=lambda text, iid=item_id: self._log(iid, "thinking", text),
            on_complete=lambda result, iid=item_id: self._on_agent_complete(iid, result),
            on_error=lambda err, iid=item_id: self._on_agent_error(iid, err),
            on_clarify=lambda prompt, choices, iid=item_id: self._on_clarify(iid, prompt, choices),
            on_create_todo=lambda title, desc, iid=item_id: self._on_create_todo(iid, title, desc),
        )

        self.sessions[item_id] = session

        # Resume conversation with feedback in background
        resume_id = item.get("session_id")
        asyncio.create_task(self._run_agent(item_id, session, feedback, resume_session_id=resume_id))

        return item

    async def submit_clarification(self, item_id: str, response: str) -> dict:
        """Submit a clarification response to a waiting agent."""
        # Update clarification record
        async with self.db.connect() as conn:
            await conn.execute(
                "UPDATE clarifications SET response = ?, answered_at = datetime('now') "
                "WHERE item_id = ? AND response IS NULL",
                (response, item_id),
            )
            await conn.commit()

        # Signal the waiting _on_clarify coroutine
        self._clarify_responses[item_id] = response
        event = self._clarify_events.get(item_id)
        if event:
            event.set()

        # The _on_clarify callback handles moving item back to doing
        return {"ok": True}

    async def shutdown(self):
        """Gracefully stop all running agents."""
        for item_id, session in list(self.sessions.items()):
            try:
                await session.cancel()
            except Exception:
                pass
        self.sessions.clear()
