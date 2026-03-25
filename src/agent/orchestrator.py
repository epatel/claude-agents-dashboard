import asyncio
import json
import logging
from pathlib import Path

from ..database import Database
from ..web.websocket import ConnectionManager
from ..git.worktree import create_worktree, remove_worktree, cleanup_worktree
from ..git.operations import merge_branch
from .session import AgentSession, AgentResult
from .commit_message import create_commit_message_server
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
        self._agent_tasks: dict[str, asyncio.Task] = {}  # item_id -> _run_agent task
        self._clarify_events: dict[str, asyncio.Event] = {}
        self._clarify_responses: dict[str, str] = {}
        self._last_agent_messages: dict[str, str] = {}  # item_id -> last agent text
        self._commit_messages: dict[str, str] = {}  # item_id -> commit message from tool

    async def _cleanup_session(self, item_id: str) -> None:
        """Cancel and clean up any running agent session for an item."""
        session = self.sessions.pop(item_id, None)
        agent_task = self._agent_tasks.pop(item_id, None)
        self._last_agent_messages.pop(item_id, None)

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

    async def _on_set_commit_message(self, item_id: str, message: str) -> str:
        """Called when agent uses set_commit_message tool."""
        self._commit_messages[item_id] = message
        await self._log(item_id, "system", f"Commit message set: {message}")
        return f"Commit message saved: {message}"

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
        elif name == "set_commit_message":
            msg = inp.get("message", "")
            return f"**Commit Message** {msg}"
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
            # If column_name is being changed, assign next position in target column
            if "column_name" in kwargs and "position" not in kwargs:
                target_column = kwargs["column_name"]
                cursor = await conn.execute(
                    "SELECT COALESCE(MAX(position), -1) + 1 FROM items WHERE column_name = ?",
                    (target_column,)
                )
                row = await cursor.fetchone()
                kwargs["position"] = row[0]

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
        # Clean up any existing session for this item
        await self._cleanup_session(item_id)

        # Get item
        async with self.db.connect() as conn:
            cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
            item = dict(await cursor.fetchone())

        config = await self._get_agent_config()
        branch_name = f"agent/{item_id}"

        # Reuse existing worktree if it exists, otherwise create new
        base_branch = item.get("base_branch")  # Preserve from previous run
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
            worktree_path, base_branch = await create_worktree(
                self.target_project, self.worktree_dir, branch_name
            )

        # Update item state
        item = await self._update_item(
            item_id,
            column_name="doing",
            status="running",
            branch_name=branch_name,
            worktree_path=str(worktree_path),
            base_branch=base_branch,
        )

        await self._log(item_id, "system", "Agent started")

        # Determine which model to use: item-specific model, or fall back to global config
        model = item.get("model") or config.get("model")

        # Create session using helper method
        session = self._create_session(item_id, worktree_path, config, model)

        self.sessions[item_id] = session

        # Build the prompt from item description
        prompt = f"Task: {item['title']}\n\n{item['description']}"

        # Fetch attachments for this item
        attachments = []
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT * FROM attachments WHERE item_id = ? ORDER BY created_at",
                (item_id,),
            )
            rows = await cursor.fetchall()
            attachments = [dict(row) for row in rows]
            if attachments:
                await self._log(item_id, "system", f"Found {len(attachments)} image attachment(s) for agent")

        # Launch agent in background so HTTP response returns immediately
        task = asyncio.create_task(self._run_agent(item_id, session, prompt, attachments))
        self._agent_tasks[item_id] = task

        return item

    async def _run_agent(self, item_id: str, session: AgentSession, prompt: str, attachments: list[dict] | None = None, resume_session_id: str | None = None):
        """Run agent session in background."""
        try:
            await session.start(prompt, attachments=attachments, resume_session_id=resume_session_id)
        except Exception as e:
            logger.exception(f"Agent failed to start for {item_id}")
            await self._on_agent_error(item_id, str(e))

    async def _on_agent_complete(self, item_id: str, result: AgentResult):
        """Called when agent finishes."""
        session = self.sessions.pop(item_id, None)
        self._agent_tasks.pop(item_id, None)
        self._last_agent_messages.pop(item_id, None)

        # If session was already removed (e.g. by cancel_agent), skip state update
        if session is None:
            return

        # Ensure the subprocess is terminated
        try:
            await session.cancel()
        except Exception:
            pass

        # Save token usage statistics
        await self._save_token_usage(item_id, result)

        if result.success:
            # Create enhanced log message with both cost and token info
            log_parts = ["Agent completed"]
            if result.cost_usd:
                log_parts.append(f"cost: ${result.cost_usd:.4f}")
            if result.total_tokens:
                log_parts.append(f"tokens: {result.total_tokens:,}")
            elif result.input_tokens and result.output_tokens:
                log_parts.append(f"tokens: {result.input_tokens + result.output_tokens:,}")

            log_message = f"{log_parts[0]} ({', '.join(log_parts[1:])})" if len(log_parts) > 1 else log_parts[0]
            await self._log(item_id, "system", log_message)

            # Use commit message set via the set_commit_message tool
            commit_message = self._commit_messages.pop(item_id, None)

            update_kwargs = dict(
                column_name="review",
                status=None,
                session_id=result.session_id,
            )
            if commit_message:
                update_kwargs["commit_message"] = commit_message

            await self._update_item(item_id, **update_kwargs)
        else:
            await self._log(item_id, "error", f"Agent failed: {result.error}")
            await self._update_item(item_id, status="failed")

    async def _on_agent_error(self, item_id: str, error: str):
        """Called when agent crashes."""
        session = self.sessions.pop(item_id, None)
        self._agent_tasks.pop(item_id, None)

        # If session was already removed (e.g. by cancel_agent), skip state update
        if session is None:
            return

        await self._log(item_id, "error", f"Agent error: {error}")
        await self._update_item(item_id, status="failed")

    async def cancel_agent(self, item_id: str) -> dict:
        """Cancel a running agent."""
        await self._cleanup_session(item_id)

        await self._log(item_id, "system", "Agent cancelled by user")
        return await self._update_item(
            item_id,
            column_name="todo",
            status="cancelled",
        )

    async def retry_agent(self, item_id: str) -> dict:
        """Retry a failed agent — restart from scratch in existing worktree."""
        await self._cleanup_session(item_id)

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

        return await self.start_agent(item_id)

    async def approve_item(self, item_id: str) -> dict:
        """Approve a reviewed item — merge back into the base branch."""
        async with self.db.connect() as conn:
            cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
            item = dict(await cursor.fetchone())

        branch = item["branch_name"]
        base_branch = item.get("base_branch")  # Branch the worktree was created from
        worktree_path = Path(item["worktree_path"]) if item.get("worktree_path") else None
        commit_msg = item.get("commit_message")

        try:
            success, message = await merge_branch(
                self.target_project, branch, base=base_branch,
                worktree_path=worktree_path,
                commit_message=commit_msg,
            )

            if success:
                target = base_branch or "current branch"
                await self._log(item_id, "system", f"Merged {branch} into {target}")

                # Clean up worktree
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
                # TODO: spawn merge resolution agent
                return await self._update_item(item_id, status="resolving_conflicts")

        except asyncio.TimeoutError as e:
            # Handle timeout during merge operation
            await self._log(item_id, "system", f"Merge operation timed out: {str(e)}")
            return await self._update_item(item_id, status="merge_timeout")
        except Exception as e:
            # Handle other unexpected errors
            await self._log(item_id, "system", f"Unexpected error during merge: {str(e)}")
            return await self._update_item(item_id, status="merge_error")

    async def request_changes(self, item_id: str, comments: list[str]) -> dict:
        """Send review comments back to the agent."""
        # Clean up any existing session before starting a new one
        await self._cleanup_session(item_id)

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
        worktree_path = Path(item["worktree_path"])

        # Create session using helper method
        session = self._create_session(item_id, worktree_path, config)

        self.sessions[item_id] = session

        # Fetch attachments for this item (in case they're needed for context)
        attachments = []
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT * FROM attachments WHERE item_id = ? ORDER BY created_at",
                (item_id,),
            )
            rows = await cursor.fetchall()
            attachments = [dict(row) for row in rows]

        # Resume conversation with feedback in background
        resume_id = item.get("session_id")
        task = asyncio.create_task(self._run_agent(item_id, session, feedback, attachments, resume_session_id=resume_id))
        self._agent_tasks[item_id] = task

        return item

    async def cancel_review(self, item_id: str) -> dict:
        """Cancel a review - discard changes and move item back to todo."""
        # Clean up any running agent session (e.g., from request_changes)
        await self._cleanup_session(item_id)

        async with self.db.connect() as conn:
            cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
            item = dict(await cursor.fetchone())

        # Clean up worktree
        branch = item["branch_name"]
        worktree_path = Path(item["worktree_path"]) if item.get("worktree_path") else None
        if worktree_path and branch:
            try:
                await cleanup_worktree(self.target_project, worktree_path, branch)
                await self._log(item_id, "system", f"Cleaned up worktree and branch {branch}")
            except Exception as e:
                logger.warning(f"Worktree cleanup failed: {e}")
                await self._log(item_id, "system", f"Worktree cleanup failed: {e}")

        await self._log(item_id, "user_action", "Review cancelled - work discarded")

        # Move item back to todo, clear status and worktree
        return await self._update_item(
            item_id,
            column_name="todo",
            status=None,
            worktree_path=None,
        )

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

    def _create_session(self, item_id: str, worktree_path: Path, config: dict, model: str | None = None) -> AgentSession:
        """Create an AgentSession with standard callbacks and configuration."""
        # Use provided model or fall back to config model
        session_model = model or config.get("model")

        # Build system prompt with project context
        system_prompt = config.get("system_prompt", "") or ""
        project_context = config.get("project_context", "") or ""
        if project_context:
            system_prompt = f"{system_prompt}\n\nProject context:\n{project_context}"

        # Create message callback
        async def _on_message(text: str, iid: str = item_id):
            self._last_agent_messages[iid] = text
            await self._log(iid, "agent_message", text)

        # Parse plugins from config
        plugins = self._parse_plugins(config.get("plugins"))

        return AgentSession(
            worktree_path=worktree_path,
            system_prompt=system_prompt,
            model=session_model,
            on_message=_on_message,
            on_tool_use=lambda name, inp, iid=item_id: self._log(
                iid, "tool_use", self._format_tool_use(name, inp), json.dumps(inp)
            ),
            on_thinking=lambda text, iid=item_id: self._log(iid, "thinking", text),
            on_complete=lambda result, iid=item_id: self._on_agent_complete(iid, result),
            on_error=lambda err, iid=item_id: self._on_agent_error(iid, err),
            on_clarify=lambda prompt, choices, iid=item_id: self._on_clarify(iid, prompt, choices),
            on_create_todo=lambda title, desc, iid=item_id: self._on_create_todo(iid, title, desc),
            on_set_commit_message=lambda msg, iid=item_id: self._on_set_commit_message(iid, msg),
            mcp_servers=config.get("mcp_servers"),
            mcp_enabled=config.get("mcp_enabled", False),
            plugins=plugins,
        )

    def _parse_plugins(self, plugins_json: str | None) -> list[dict] | None:
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

    async def _save_token_usage(self, item_id: str, result: AgentResult):
        """Save token usage statistics to the database."""
        # Only save if we have meaningful data
        if not any([result.input_tokens, result.output_tokens, result.total_tokens, result.cost_usd]):
            return

        async with self.db.connect() as conn:
            await conn.execute("""
                INSERT INTO token_usage
                (item_id, session_id, input_tokens, output_tokens, total_tokens, cost_usd)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                item_id,
                result.session_id,
                result.input_tokens,
                result.output_tokens,
                result.total_tokens,
                result.cost_usd
            ))
            await conn.commit()

    async def delete_item(self, item_id: str) -> dict:
        """Delete an item and clean up all associated resources."""
        # Clean up any running agent session
        await self._cleanup_session(item_id)

        # Get item info for cleanup before deletion
        async with self.db.connect() as conn:
            cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
            item_row = await cursor.fetchone()
            item = dict(item_row) if item_row else None

            # Delete attachment files
            cursor2 = await conn.execute("SELECT asset_path FROM attachments WHERE item_id = ?", (item_id,))
            for row in await cursor2.fetchall():
                p = Path(row[0])
                if p.exists():
                    p.unlink()

            # Delete all related records
            await conn.execute("DELETE FROM attachments WHERE item_id = ?", (item_id,))
            await conn.execute("DELETE FROM work_log WHERE item_id = ?", (item_id,))
            await conn.execute("DELETE FROM review_comments WHERE item_id = ?", (item_id,))
            await conn.execute("DELETE FROM clarifications WHERE item_id = ?", (item_id,))
            await conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
            await conn.commit()

        # Clean up worktree and branch if they exist
        if item and item.get("worktree_path") and item.get("branch_name"):
            try:
                await cleanup_worktree(
                    self.target_project,
                    Path(item["worktree_path"]),
                    item["branch_name"],
                )
            except Exception as e:
                logger.warning(f"Worktree cleanup failed for item {item_id}: {e}")

        # Broadcast deletion event
        await self.ws_manager.broadcast("item_deleted", {"id": item_id})

        return {"ok": True}

    async def shutdown(self):
        """Gracefully stop all running agents."""
        item_ids = list(set(list(self.sessions.keys()) + list(self._agent_tasks.keys())))
        for item_id in item_ids:
            try:
                await self._cleanup_session(item_id)
            except Exception:
                pass
