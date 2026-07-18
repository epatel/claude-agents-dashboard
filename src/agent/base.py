"""Abstract contract for provider-backed agent sessions.

The dashboard drives every agent run through this surface. A concrete session
(e.g. the Claude Agent SDK-backed one in `session.py`) owns its provider's
client and receive loop internally; only dashboard-owned types cross the
boundary:

- Events reach the dashboard through the `on_*` async callbacks passed to the
  concrete constructor (`on_message(text: str)`, `on_tool_use(name, input)`,
  `on_thinking(text)`, `on_complete(AgentResult)`, `on_error(text)`, plus the
  tool-backing callbacks such as `on_clarify`, `on_create_todo`, ...). The
  constructor is deliberately NOT part of the contract — `SessionService`
  constructs the concrete class with provider-specific kwargs.
- `current_session_id` is read externally (pause/resume flows) and also
  WRITTEN externally (see `command_filter.py`), so it must remain a plain
  writable attribute on every implementation.
- `on_error` is read (and awaited) directly by `SessionService`.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class AgentResult:
    success: bool
    session_id: str | None = None
    error: str | None = None
    cost_usd: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    # HTTP status of a failing API call (429/500/529, etc.) when is_error.
    # Safe-to-log classifier for API failures vs. agent/task errors.
    api_error_status: int | None = None


class AbstractAgentSession(ABC):
    """Contract every agent-session implementation must satisfy."""

    current_session_id: str | None
    on_error: object | None

    @abstractmethod
    async def start(
        self,
        prompt: str,
        attachments: list[dict] | None = None,
        resume_session_id: str | None = None,
    ) -> None:
        """Start the agent run; stream events via the on_* callbacks."""

    @abstractmethod
    async def cancel(self) -> None:
        """Stop the run and release provider resources."""
