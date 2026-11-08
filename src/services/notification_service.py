"""Notification service for WebSocket broadcasting and logging."""

import json
import logging
from typing import Any, Dict, List, Optional

from ..web.websocket import ConnectionManager

logger = logging.getLogger(__name__)


def _truncated(text: str, limit: int) -> str:
    """`text` cut to `limit` characters plus "..." when longer."""
    return text[:limit] + "..." if len(text) > limit else text


# Work-log line for each known tool, from its input.
_TOOL_FORMATTERS = {
    "Write": lambda inp: f"**Write** `{inp.get('file_path', '')}`",
    "Edit": lambda inp: f"**Edit** `{inp.get('file_path', '')}`",
    "Read": lambda inp: f"**Read** `{inp.get('file_path', '')}`",
    "Bash": lambda inp: f"**Bash** `{_truncated(inp.get('command', ''), 120)}`",
    "Glob": lambda inp: f"**Glob** `{inp.get('pattern', '')}`",
    "Grep": lambda inp: f"**Grep** `{inp.get('pattern', '')}` in `{inp.get('path', '.')}`",
    "create_todo": lambda inp: f"**Create Todo** {inp.get('title', '')}",
    "set_commit_message": lambda inp: f"**Commit Message** {inp.get('message', '')}",
    "create_shortcut": lambda inp: f"**Create Shortcut** {inp.get('name', '')} → `{inp.get('command', '')}`",
    "ask_user": lambda inp: f"**Ask User** {_truncated(inp.get('question', ''), 100)}",
}


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

    async def broadcast_graph_event(self, event_type: str, data: Dict[str, Any]):
        """Broadcast a graphify event (e.g. graph_build_progress, graph_ready)."""
        await self.ws_manager.broadcast(event_type, data)

    async def broadcast_agent_log(self, item_id: str, entry_type: str, content: str):
        """Broadcast agent log event."""
        await self.ws_manager.broadcast("agent_log", {
            "item_id": item_id,
            "entry_type": entry_type,
            "content": content,
        })

    async def broadcast_clarification_requested(
        self,
        item_id: str,
        prompt: str,
        choices: Optional[List[str]],
        context: Optional[str] = None,
    ):
        """Broadcast question request event."""
        await self.ws_manager.broadcast("clarification_requested", {
            "item_id": item_id,
            "prompt": prompt,
            "choices": json.dumps(choices) if choices else None,
            "context": context,
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
        formatter = _TOOL_FORMATTERS.get(name)
        if formatter:
            return formatter(inp)
        return f"**{name}** {_truncated(str(inp), 100)}"

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