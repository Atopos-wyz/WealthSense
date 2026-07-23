from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.schemas.common import (
    AgentId,
    ErrorDetail,
    OperationIntent,
    OperationStatus,
    RiskDecision,
)


class OperatorContext(BaseModel):
    operator_id: str
    role: str
    organization_id: str = "ORG001"


class ChatOperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    session_id: str
    task_id: str | None = None
    customer_id: str | None = None
    message: str = Field(min_length=1, max_length=2000)
    known_params: dict[str, Any] = Field(default_factory=dict)


class ConfirmOperationRequest(BaseModel):
    request_id: str
    confirmer_id: str
    operation_version: int = Field(ge=1)
    params_hash: str
    confirmation_method: Literal["chat", "otp", "transaction_password"] = "chat"


class CancelOperationRequest(BaseModel):
    request_id: str
    cancelled_by: str
    reason: str = Field(min_length=1, max_length=500)


class PurchaseParams(BaseModel):
    customer_id: str
    product_id: str
    account_id: str
    amount: Decimal = Field(gt=0)
    currency: str = "CNY"


class RedeemParams(BaseModel):
    customer_id: str
    holding_id: str
    redeem_type: Literal["all", "partial"]
    shares: Decimal | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_partial_shares(self) -> "RedeemParams":
        if self.redeem_type == "partial" and self.shares is None:
            raise ValueError("partial redemption requires shares")
        return self


class TransferParams(BaseModel):
    customer_id: str
    from_account_id: str
    to_account_id: str
    amount: Decimal = Field(gt=0)
    currency: str = "CNY"


class RiskReassessmentParams(BaseModel):
    customer_id: str
    questionnaire_version: str
    answers: dict[str, str] = Field(min_length=1)


class UpdateProfileParams(BaseModel):
    customer_id: str
    field_name: Literal["phone", "address", "email"]
    new_value: str = Field(min_length=1, max_length=500)


class ProductQueryParams(BaseModel):
    product_id: str
    fields: list[str] = Field(default_factory=lambda: ["name", "status", "net_value"])


class SuspiciousReportParams(BaseModel):
    customer_id: str
    transaction_id: str
    reason: str = Field(min_length=3, max_length=1000)
    evidence_refs: list[str] = Field(default_factory=list)


class WorkOrderParams(BaseModel):
    customer_id: str
    work_order_type: str
    description: str = Field(min_length=3, max_length=2000)
    priority: Literal["low", "medium", "high", "urgent"] = "medium"


OPERATION_PARAM_MODELS: dict[OperationIntent, type[BaseModel]] = {
    OperationIntent.PURCHASE: PurchaseParams,
    OperationIntent.REDEEM: RedeemParams,
    OperationIntent.TRANSFER: TransferParams,
    OperationIntent.RISK_REASSESSMENT: RiskReassessmentParams,
    OperationIntent.UPDATE_PROFILE: UpdateProfileParams,
    OperationIntent.PRODUCT_QUERY: ProductQueryParams,
    OperationIntent.SUSPICIOUS_REPORT: SuspiciousReportParams,
    OperationIntent.CREATE_WORK_ORDER: WorkOrderParams,
}


class RiskReviewResult(BaseModel):
    event_id: str
    operation_id: str
    operation_version: int = Field(ge=1)
    decision: RiskDecision
    risk_level: str | None = None
    rule_hits: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    reason: str = ""
    occurred_at: datetime
    expires_at: datetime | None = None


class OperationResponse(BaseModel):
    request_id: str
    operation_id: str
    version: int
    intent: OperationIntent
    status: OperationStatus
    source_agent: AgentId
    params: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    confirmation_required: bool = False
    confirmation_expires_at: datetime | None = None
    result: dict[str, Any] | None = None
    reply: str
    error: ErrorDetail | None = None

    @field_validator("params", mode="before")
    @classmethod
    def stringify_decimals(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        return {
            key: str(item) if isinstance(item, Decimal) else item
            for key, item in value.items()
        }

