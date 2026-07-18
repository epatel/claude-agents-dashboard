from pydantic import BaseModel, Field, field_validator
from typing import Any, List, Optional
from datetime import datetime
import json
import uuid
from .constants import (
    DEFAULT_MODEL,
    DEFAULT_OLLAMA_BASE_URL,
    EPIC_COLORS,
    AUTO_APPROVE_OFF,
    AUTO_APPROVE_REVIEW,
    AUTO_APPROVE_MODES,
)

VALID_EPIC_COLOR_KEYS = {c["key"] for c in EPIC_COLORS}


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _coerce_auto_approve(v: Any) -> Any:
    """auto_approve graduated from a boolean to a tri-state int (0/1/2).
    Old API clients (and the JS api.js default) still send True/False — coerce
    those to the int equivalents so the API stays backward compatible:
        False -> 0 (OFF), True -> 1 (REVIEW, the original auto-approve mode).
    Reject anything outside the allowed set to fail fast on bad input."""
    if v is None:
        return v
    if isinstance(v, bool):
        return AUTO_APPROVE_REVIEW if v else AUTO_APPROVE_OFF
    if isinstance(v, int) and v in AUTO_APPROVE_MODES:
        return v
    raise ValueError(
        f"auto_approve must be one of {sorted(AUTO_APPROVE_MODES)} "
        f"(0=off, 1=with review, 2=direct); got {v!r}"
    )


class ItemCreate(BaseModel):
    title: str
    description: str = ""
    # Default None (NULL in the items table) means "use the global default
    # model". Resolution at spawn time is `item.model or config.model`, so a
    # None here correctly falls through to the configured global default
    # (e.g. an Ollama model). Baking DEFAULT_MODEL in here would shadow the
    # global default for every item created via the "Default" option.
    model: Optional[str] = None
    epic_id: Optional[str] = None
    auto_start: bool = False
    start_copy: bool = False
    auto_approve: int = AUTO_APPROVE_OFF
    # When True, the item's agent launches with `claude --chrome`, giving it
    # the Claude-in-Chrome browser tools. Off for code-only tasks.
    use_chrome: bool = False
    # Multi-repo mode: name of the subrepo this item targets. Must be one of the
    # workspace's known repos. None in single-repo mode.
    repo: Optional[str] = None

    @field_validator("auto_approve", mode="before")
    @classmethod
    def _validate_auto_approve(cls, v: Any) -> Any:
        return _coerce_auto_approve(v)


class AgentTodoCreate(BaseModel):
    """A todo created on behalf of a running agent (POST /api/items/{id}/agent-todos).

    Mirrors the create_todo MCP tool's inputs — including `requires`
    (dependency item ids) and `autostart` — and runs through the same
    workflow callback, unlike the plain board POST /api/items.
    """
    title: str
    description: str = ""
    epic_id: Optional[str] = None
    requires: List[str] = []
    autostart: bool = False
    auto_approve: int = AUTO_APPROVE_OFF
    use_chrome: bool = False

    @field_validator("auto_approve", mode="before")
    @classmethod
    def _validate_auto_approve(cls, v: Any) -> Any:
        return _coerce_auto_approve(v)


class ItemUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    column_name: Optional[str] = None
    position: Optional[int] = None
    status: Optional[str] = None
    model: Optional[str] = None
    epic_id: Optional[str] = None
    auto_start: Optional[bool] = None
    start_copy: Optional[bool] = None
    auto_approve: Optional[int] = None
    use_chrome: Optional[bool] = None

    @field_validator("auto_approve", mode="before")
    @classmethod
    def _validate_auto_approve(cls, v: Any) -> Any:
        return _coerce_auto_approve(v)


class EpicCreate(BaseModel):
    title: str
    color: str = "blue"

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str) -> str:
        if v not in VALID_EPIC_COLOR_KEYS:
            raise ValueError(
                f"Invalid epic color '{v}'. Must be one of: {', '.join(sorted(VALID_EPIC_COLOR_KEYS))}"
            )
        return v


class EpicUpdate(BaseModel):
    title: Optional[str] = None
    color: Optional[str] = None
    position: Optional[int] = None

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_EPIC_COLOR_KEYS:
            raise ValueError(
                f"Invalid epic color '{v}'. Must be one of: {', '.join(sorted(VALID_EPIC_COLOR_KEYS))}"
            )
        return v


class ItemMove(BaseModel):
    column_name: str
    position: int


class Item(BaseModel):
    id: str
    title: str
    description: str
    column_name: str
    position: int
    status: Optional[str]
    branch_name: Optional[str]
    worktree_path: Optional[str]
    session_id: Optional[str]
    model: Optional[str]
    repo: Optional[str] = None
    created_at: str
    updated_at: str


class WorkLogEntry(BaseModel):
    id: int
    item_id: str
    timestamp: str
    entry_type: str
    content: str
    metadata: Optional[str]


class ReviewComment(BaseModel):
    id: int
    item_id: str
    file_path: Optional[str]
    line_number: Optional[int]
    content: str
    created_at: str


class ClarificationRequest(BaseModel):
    id: int
    item_id: str
    prompt: str
    choices: Optional[str]
    allow_text: bool
    response: Optional[str]
    created_at: str
    answered_at: Optional[str]


class ClarificationResponse(BaseModel):
    response: str


class TokenUsage(BaseModel):
    id: int
    item_id: str
    session_id: Optional[str]
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    total_tokens: Optional[int]
    cost_usd: Optional[float]
    completed_at: str


class AgentConfig(BaseModel):
    """Agent configuration. The five list/dict fields below were previously
    typed as `Optional[str]` holding JSON — they were promoted to real
    Python types. Validators tolerate JSON strings on input (DB rows
    arrive as TEXT) so this model is safe to construct from either an
    HTTP body (already parsed) or a SQLite row (raw JSON strings)."""

    system_prompt: Optional[str] = ""
    tools: list[str] = Field(default_factory=list)
    model: str = DEFAULT_MODEL
    project_context: Optional[str] = ""
    mcp_servers: dict[str, Any] = Field(default_factory=dict)
    mcp_enabled: bool = False
    plugins: list[Any] = Field(default_factory=list)
    allowed_commands: list[str] = Field(default_factory=list)
    bash_yolo: bool = False
    allowed_builtin_tools: list[str] = Field(default_factory=list)
    flame_enabled: bool = True
    flame_intensity_multiplier: float = 1.0
    ollama_enabled: bool = False
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL
    ollama_load_claude_md: bool = False
    wip_limit: int = 0
    graphify_enabled: bool = False
    graphify_auto_refresh: bool = True
    graphify_backend: str = "ast"
    enabled_skills: list[str] = Field(default_factory=list)

    @field_validator("tools", "plugins", "allowed_commands", "allowed_builtin_tools", "enabled_skills", mode="before")
    @classmethod
    def _parse_json_list(cls, v: Any) -> Any:
        if v is None or v == "":
            return []
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return []
        return v

    @field_validator("mcp_servers", mode="before")
    @classmethod
    def _parse_json_dict(cls, v: Any) -> Any:
        if v is None or v == "":
            return {}
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return {}
        return v
