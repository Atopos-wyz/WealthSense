"""投顾 Agent 请求、路由与响应模型。"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import Field, field_validator

from app.models.schemas.common import DecimalJsonModel, RiskLevel
from app.models.schemas.event import EventPublishReceipt
from app.models.schemas.response import PublicSchema


class AdvisorIntent(StrEnum):
    PRODUCT_RECOMMENDATION = "PRODUCT_RECOMMENDATION"
    HOLDING_ANALYSIS = "HOLDING_ANALYSIS"
    ASSET_ALLOCATION = "ASSET_ALLOCATION"
    PRODUCT_COMPARISON = "PRODUCT_COMPARISON"
    RISK_ASSESSMENT_REQUIRED = "RISK_ASSESSMENT_REQUIRED"
    UNKNOWN = "UNKNOWN"


class AdvisorRoute(StrEnum):
    ADVISOR = "ADVISOR"
    RISK_AGENT = "RISK_AGENT"


class ProductRiskLevel(StrEnum):
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    R4 = "R4"
    R5 = "R5"


class AdvisorChatRequest(PublicSchema):
    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=4000)
    user_id: str = Field(min_length=1, max_length=64)
    customer_id: int = Field(gt=0)
    intent_hint: AdvisorIntent | None = None
    product_ids: list[int] = Field(default_factory=list, max_length=20)
    comparison_customer_ids: list[int] = Field(
        default_factory=list,
        max_length=10,
    )
    top_k: int = Field(default=5, ge=1, le=20)

    @field_validator("product_ids", "comparison_customer_ids")
    @classmethod
    def unique_positive_ids(cls, values: list[int]) -> list[int]:
        if any(value <= 0 for value in values):
            raise ValueError("ID 必须为正整数")
        return list(dict.fromkeys(values))


class ProductRecommendation(DecimalJsonModel):
    product_id: int
    product_code: str
    product_name: str
    product_type: str
    risk_level: ProductRiskLevel
    expected_return: Decimal | None = None
    min_amount: Decimal
    term_days: int
    fund_manager: str | None = None
    industry: str | None = None
    market: str | None = None
    score: Decimal
    reason: str
    graph_context: dict[str, Any] = Field(default_factory=dict)


class HoldingAnalysis(DecimalJsonModel):
    total_value: Decimal
    total_profit_loss: Decimal
    holding_count: int
    product_concentration: dict[str, Decimal] = Field(default_factory=dict)
    industry_concentration: dict[str, Decimal] = Field(default_factory=dict)
    risk_exposure: dict[str, Decimal] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class AllocationItem(DecimalJsonModel):
    asset_type: str
    current_ratio: Decimal
    target_ratio: Decimal
    adjustment: Decimal
    suggestion: str


class AssetAllocationAdvice(DecimalJsonModel):
    risk_level: RiskLevel
    items: list[AllocationItem]
    summary: str


class ComparisonItem(DecimalJsonModel):
    product_id: int
    product_name: str
    risk_level: ProductRiskLevel
    expected_return: Decimal | None = None
    term_days: int
    min_amount: Decimal
    differences: list[str] = Field(default_factory=list)


class ComparisonReport(PublicSchema):
    products: list[ComparisonItem] = Field(default_factory=list)
    customer_summaries: list[dict[str, Any]] = Field(default_factory=list)
    conclusion: str


class AdvisorChatResponse(PublicSchema):
    reply: str
    recommendations: list[ProductRecommendation] = Field(
        default_factory=list
    )
    reasoning: list[str] = Field(default_factory=list)
    session_id: str
    intent: AdvisorIntent
    route: AdvisorRoute = AdvisorRoute.ADVISOR
    profile_found: bool = True
    holding_analysis: HoldingAnalysis | None = None
    allocation_advice: AssetAllocationAdvice | None = None
    comparison_report: ComparisonReport | None = None
    event_delivery: list[EventPublishReceipt] = Field(default_factory=list)


class AdvisorStreamEvent(PublicSchema):
    event: str
    data: dict[str, Any]
