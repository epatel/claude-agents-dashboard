from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
import uuid
from .constants import DEFAULT_MODEL


def new_id() -> str:
    return uuid.uuid4().hex[:12]


class ItemCreate(BaseModel):
    title: str
    description: str = ""
    model: Optional[str] = None


class ItemUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    column_name: Optional[str] = None
    position: Optional[int] = None
    status: Optional[str] = None
    model: Optional[str] = None


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
    system_prompt: Optional[str] = ""
    tools: Optional[str] = "[]"
    model: str = DEFAULT_MODEL
    project_context: Optional[str] = ""
    mcp_servers: Optional[str] = "{}"
    mcp_enabled: bool = False
    plugins: Optional[str] = "[]"
    allowed_commands: Optional[str] = "[]"
    bash_yolo: bool = False
