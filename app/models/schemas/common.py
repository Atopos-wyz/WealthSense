"""API 公共模型。"""

from datetime import datetime, timezone
from enum import StrEnum
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.models.schemas.response import PublicSchema


class DecimalJsonModel(PublicSchema):
    """将 Decimal 以 JSON 数值返回，匹配接口文档示例。"""

    @field_serializer("*", when_used="json", check_fields=False)
    def serialize_decimal(self, value):
        return float(value) if isinstance(value, Decimal) else value


class RiskLevel(StrEnum):
    C1 = "C1"
    C2 = "C2"
    C3 = "C3"
    C4 = "C4"
    C5 = "C5"


class DataSource(StrEnum):
    RISK_QUESTIONNAIRE = "RISK_QUESTIONNAIRE"
    AI_CONVERSATION = "AI_CONVERSATION"
    USER_DECLARED = "USER_DECLARED"
    USER_CONFIRMED = "USER_CONFIRMED"
    KYC = "KYC"
    MANUAL_VERIFIED = "MANUAL_VERIFIED"
    HOLDINGS = "HOLDINGS"
    PROFILE_SERVICE = "PROFILE_SERVICE"
    SYSTEM_POLICY = "SYSTEM_POLICY"


SOURCE_CONFIDENCE: dict[DataSource, float] = {
    DataSource.RISK_QUESTIONNAIRE: 0.90,
    DataSource.MANUAL_VERIFIED: 0.90,
    DataSource.KYC: 0.85,
    DataSource.HOLDINGS: 0.85,
    DataSource.PROFILE_SERVICE: 0.85,
    DataSource.SYSTEM_POLICY: 0.90,
    DataSource.USER_CONFIRMED: 0.80,
    DataSource.AI_CONVERSATION: 0.60,
    DataSource.USER_DECLARED: 0.40,
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentId(StrEnum):
    CUSTOMER = "customer"
    ADVISOR = "advisor"
    RISK = "risk"
    ANALYST = "analyst"
    OPERATOR = "operator"


class OperationIntent(StrEnum):
    PURCHASE = "purchase"
    REDEEM = "redeem"
    TRANSFER = "transfer"
    RISK_REASSESSMENT = "risk_reassessment"
    UPDATE_PROFILE = "update_profile"
    PRODUCT_QUERY = "product_query"
    SUSPICIOUS_REPORT = "suspicious_report"
    CREATE_WORK_ORDER = "create_work_order"
    UNKNOWN = "unknown"


class OperationStatus(StrEnum):
    DRAFT = "draft"
    RESOLVING_ENTITIES = "resolving_entities"
    VALIDATING = "validating"
    NEED_MORE_INFORMATION = "need_more_information"
    PERMISSION_DENIED = "permission_denied"
    VALIDATION_FAILED = "validation_failed"
    WAITING_RISK_REVIEW = "waiting_risk_review"
    RISK_APPROVED = "risk_approved"
    RISK_REJECTED = "risk_rejected"
    RISK_REVIEW_TIMEOUT = "risk_review_timeout"
    PENDING_CONFIRMATION = "pending_confirmation"
    CONFIRMED = "confirmed"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PENDING_VERIFICATION = "pending_verification"
    MANUAL_REVIEW = "manual_review"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class RiskDecision(StrEnum):
    APPROVED = "approved"
    APPROVED_WITH_WARNING = "approved_with_warning"
    REJECTED = "rejected"
    MANUAL_REVIEW = "manual_review"


class ErrorDetail(BaseModel):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class AgentEvent(BaseModel):
    """Stable event envelope shared by all agents."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    event_type: str
    source_agent: AgentId
    target_agents: list[AgentId]
    correlation_id: str | None = None
    operation_id: str | None = None
    task_id: str | None = None
    session_id: str | None = None
    operator_id: str | None = None
    customer_id: str | None = None
    intent: OperationIntent | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime | None = None
    schema_version: str = "1.0"
    signature: str | None = None
