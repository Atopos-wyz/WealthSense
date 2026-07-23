"""事件载荷。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class RiskAlertEvent(BaseModel):
    event_type: str = "risk_alert"
    alert_id: int
    customer_id: str
    alert_level: str
    trigger_rules: list[str]
    confidence: float
    llm_review: str | None = None
    reason_summary: str | None = None
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_publish_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
