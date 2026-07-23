"""投顾及画像模块的事件模型。"""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentEventType(StrEnum):
    ASSESSMENT_COMPLETED = "assessment_completed"
    PROFILE_UPDATED = "profile_updated"


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

    event_type: str
    source_agent: AgentType
    target_agents: list[AgentType] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = None
    customer_id: int | None = None
    correlation_id: str | None = None
    deduplication_key: str | None = None
    occurred_at: datetime = Field(default_factory=_utc_now)
