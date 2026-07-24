"""风控预警实体与内存记录模型。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.entities.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RiskAlertEntity(Base):
    """MySQL 表 fin_risk_alert（可选后端）。"""

    __tablename__ = "fin_risk_alert"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(String(64), index=True)
    record_type: Mapped[str] = mapped_column(String(32))  # alert | audit_clean
    alert_level: Mapped[str | None] = mapped_column(String(8), nullable=True)
    hit_rules_json: Mapped[str] = mapped_column(Text, default="[]")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    llm_review: Mapped[str | None] = mapped_column(String(64), nullable=True)
    llm_conflict: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="未处理")
    work_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    broadcasted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RiskAlertRecord:
    """跨后端统一的预警/审计记录（内存与 DAO 互转）。"""

    __slots__ = (
        "id",
        "customer_id",
        "record_type",
        "alert_level",
        "hit_rules",
        "reason",
        "confidence",
        "llm_review",
        "llm_conflict",
        "status",
        "work_order_id",
        "broadcasted",
        "created_at",
        "extra",
    )

    def __init__(
        self,
        *,
        id: int,
        customer_id: str,
        record_type: str,
        alert_level: str | None,
        hit_rules: list[dict[str, Any]],
        reason: str | None,
        confidence: float,
        llm_review: str | None,
        llm_conflict: bool = False,
        status: str = "未处理",
        work_order_id: str | None = None,
        broadcasted: bool = False,
        created_at: datetime | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.id = id
        self.customer_id = customer_id
        self.record_type = record_type
        self.alert_level = alert_level
        self.hit_rules = hit_rules
        self.reason = reason
        self.confidence = confidence
        self.llm_review = llm_review
        self.llm_conflict = llm_conflict
        self.status = status
        self.work_order_id = work_order_id
        self.broadcasted = broadcasted
        self.created_at = created_at or utc_now()
        self.extra = extra or {}
