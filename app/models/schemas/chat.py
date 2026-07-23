"""Agent 对话请求与响应模型。"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field

from app.models.schemas.response import PublicSchema


class AgentType(str, Enum):
    CUSTOMER = "customer"
    ANALYST = "analyst"


class ChatRequest(PublicSchema):
    agent_type: AgentType = AgentType.CUSTOMER
    session_id: str = Field(min_length=1, max_length=64)
    user_id: str = Field(min_length=1, max_length=64)
    customer_id: int | None = None
    message: str = Field(min_length=1, max_length=4000)
    context: dict[str, Any] = Field(default_factory=dict)


class SourceReference(PublicSchema):
    source: str
    title: str
    score: float
    source_id: int


class ToolCallRecord(PublicSchema):
    tool_name: str
    status: str
    execution_time_ms: float
    parameters: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(PublicSchema):
    reply: str
    source_references: list[SourceReference] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    intent: str
    confidence: float = Field(ge=0, le=1)
    suggestions: list[str] = Field(default_factory=list)
    session_id: str
    sql: str | None = None
    query_result: list[dict[str, Any]] | None = None


class SessionMessage(PublicSchema):
    role: str
    content: str
    timestamp: str
