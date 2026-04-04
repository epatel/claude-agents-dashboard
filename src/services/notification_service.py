"""Notification service for WebSocket broadcasting and logging."""

import json
import logging
from typing import Any, Dict, List, Optional

from ..web.websocket import ConnectionManager

logger = logging.getLogger(__name__)


class NotificationService:
    """Handles WebSocket notifications and event broadcasting."""

    def __init__(self, ws_manager: ConnectionManager):
        self.ws_manager = ws_manager

    async def broadcast_item_updated(self, item: Dict[str, Any], source: str = None):
        """Broadcast item update event.

        Args:
            item: The item data to broadcast.
            source: Optional source identifier (e.g. "agent") so the frontend
                    can distinguish agent-driven updates from user-driven ones.
        """
        data = {**item, "_source": source} if source else item
        await self.ws_manager.broadcast("item_updated", data)

    async def broadcast_item_created(self, item: Dict[str, Any]):
        """Broadcast item creation event."""
        await self.ws_manager.broadcast("item_created", item)

    async def broadcast_item_deleted(self, item_id: str):
        """Broadcast item deletion event."""
        await self.ws_manager.broadcast("item_deleted", {"id": item_id})

    async def broadcast_agent_log(self, item_id: str, entry_type: str, content: str):
        """Broadcast agent log event."""
        await self.ws_manager.broadcast("agent_log", {
            "item_id": item_id,
            "entry_type": entry_type,
            "content": content,
        })

    async def broadcast_clarification_requested(self, item_id: str, prompt: str, choices: Optional[List[str]]):
        """Broadcast question request event."""
        await self.ws_manager.broadcast("clarification_requested", {
            "item_id": item_id,
            "prompt": prompt,
            "choices": json.dumps(choices) if choices else None,
        })

    async def broadcast_epic_created(self, epic: Dict[str, Any]):
        """Broadcast epic creation event."""
        await self.ws_manager.broadcast("epic_created", epic)

    async def broadcast_epic_updated(self, epic: Dict[str, Any]):
        """Broadcast epic update event."""
        await self.ws_manager.broadcast("epic_updated", epic)

    async def broadcast_epic_deleted(self, epic_id: str):
        """Broadcast epic deletion event."""
        await self.ws_manager.broadcast("epic_deleted", {"id": epic_id})

    def format_tool_use(self, name: str, inp: Dict[str, Any]) -> str:
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

    def format_completion_log(self, cost_usd: Optional[float] = None,
                             total_tokens: Optional[int] = None,
                             input_tokens: Optional[int] = None,
                             output_tokens: Optional[int] = None) -> str:
        """Format completion log with cost and token information."""
        log_parts = ["Agent completed"]
        if cost_usd:
            log_parts.append(f"cost: ${cost_usd:.4f}")
        if total_tokens:
            log_parts.append(f"tokens: {total_tokens:,}")
        elif input_tokens and output_tokens:
            log_parts.append(f"tokens: {input_tokens + output_tokens:,}")

        return f"{log_parts[0]} ({', '.join(log_parts[1:])})" if len(log_parts) > 1 else log_parts[0]