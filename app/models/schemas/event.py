"""投顾及画像模块的事件模型。"""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class AgentEventType(StrEnum):
    ADVISOR_REQUESTED = "advisor.requested"
    ADVISOR_COMPLETED = "advisor.completed"
    ADVISOR_FAILED = "advisor.failed"
    PROFILE_MISSING = "profile.missing"
    ASSESSMENT_REQUIRED = "assessment.required"
    ASSESSMENT_COMPLETED = "assessment_completed"
    PROFILE_UPDATED = "profile_updated"
    RISK_ALERT = "risk_alert"


class AgentType(StrEnum):
    CUSTOMER = "customer"
    ADVISOR = "advisor"
    RISK = "risk"
    ANALYST = "analyst"
    OPERATOR = "operator"
    SYSTEM = "system"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentEvent(BaseModel):
    """投顾及画像模块的轻量事件载体。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: str
    event_version: str = "1.0"
    source_agent: AgentType
    target_agents: list[AgentType] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = None
    session_id: str | None = None
    user_id: str | None = None
    customer_id: int | None = None
    correlation_id: str | None = None
    causation_id: str | None = None
    deduplication_key: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=_utc_now)


class EventPublishReceipt(BaseModel):
    event_id: str
    published: bool
    channels: list[str] = Field(default_factory=list)
    subscriber_count: int = 0
    error: str | None = None
