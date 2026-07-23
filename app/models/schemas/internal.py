from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.models.schemas.common import (
    AgentId,
    OperationIntent,
    OperationStatus,
    utc_now,
)


@dataclass(slots=True)
class OperationRecord:
    operation_id: str
    request_id: str
    source_agent: AgentId
    session_id: str
    operator_id: str
    operator_role: str
    organization_id: str
    intent: OperationIntent
    status: OperationStatus
    raw_message: str = ""
    version: int = 1
    task_id: str | None = None
    customer_id: str | None = None
    request_event_id: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    params_hash: str = ""
    missing_fields: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    confirmation_required: bool = False
    confirmation_expires_at: datetime | None = None
    risk_request_event_id: str | None = None
    risk_result: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error_code: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    completed_at: datetime | None = None
