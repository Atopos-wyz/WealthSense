"""风险相关 Schema：适当性评估 + AML 交易监测。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.models.schemas.common import DecimalJsonModel, RiskLevel
from app.models.schemas.response import PublicSchema


# ----- 风险评估（问卷 / 适当性）-----

class RiskDimension(StrEnum):
    BASIC_CAPACITY = "BASIC_CAPACITY"
    INVESTMENT_EXPERIENCE = "INVESTMENT_EXPERIENCE"
    RISK_TOLERANCE = "RISK_TOLERANCE"
    INVESTMENT_GOAL = "INVESTMENT_GOAL"


class QuestionOption(DecimalJsonModel):
    code: Literal["A", "B", "C", "D"]
    text: str
    score: Decimal = Field(ge=0, le=100)


class RiskQuestion(BaseModel):
    id: int = Field(ge=1, le=16)
    dimension: RiskDimension
    text: str
    options: list[QuestionOption]


class QuestionnaireResponse(BaseModel):
    version: str
    title: str
    total_questions: int
    scoring_rule: str
    questions: list[RiskQuestion]


class RiskAnswer(BaseModel):
    q: int = Field(ge=1, le=16)
    a: Literal["A", "B", "C", "D"]


class AssessmentSubmitRequest(BaseModel):
    customer_id: int = Field(gt=0)
    answers: list[RiskAnswer]
    assessor_type: Literal["AI评估", "人工评估"] = "AI评估"

    @field_validator("answers")
    @classmethod
    def answers_must_not_repeat(cls, answers: list[RiskAnswer]) -> list[RiskAnswer]:
        question_ids = [answer.q for answer in answers]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("同一道题不能重复作答")
        return answers


class AssessmentAnswersRequest(BaseModel):
    answers: list[RiskAnswer]
    assessor_type: Literal["AI评估", "人工评估"] = "AI评估"


class ScoredAnswer(DecimalJsonModel):
    q: int
    a: str
    score: Decimal


class AssessmentResult(DecimalJsonModel):
    assessment_id: int
    assessment_no: str
    customer_id: int
    total_score: Decimal
    risk_level: RiskLevel
    risk_label: str
    answers: list[ScoredAnswer]
    assessment_date: datetime
    valid_until: date
    confidence_score: Decimal


class AssessmentHistoryItem(DecimalJsonModel):
    assessment_id: int
    assessment_no: str
    total_score: Decimal
    risk_level: RiskLevel
    assessor_type: str
    assessment_date: datetime
    valid_until: date
    expired: bool


class SuitabilityCheckRequest(BaseModel):
    customer_id: int = Field(gt=0)
    product_id: int = Field(gt=0)


class SuitabilityCheckResult(BaseModel):
    customer_id: int
    product_id: int
    customer_risk_level: RiskLevel
    product_risk_level: str
    maximum_allowed_product_risk: str
    allowed: bool
    warning_code: int | None = None
    reason: str


# ----- AML 交易监测 -----

class MonitorRequest(PublicSchema):
    """交易监测入参。窗口类字段由调用方预聚合传入。"""

    customer_id: str = Field(min_length=1, description="客户标识")
    amount: Decimal = Field(ge=0, description="本笔交易金额（人民币）")
    currency: str = Field(default="CNY", min_length=1)
    counterparty_country: str | None = Field(
        default=None,
        description="对手方国家/地区（ISO 或中文名）",
    )
    trade_type: str | None = Field(default=None, description="交易类型，可选")

    is_pep: bool = False
    is_pep_related: bool = False
    has_new_overseas_counterparty: bool = False
    pattern_change_ratio: float | None = Field(
        default=None,
        description="交易模式相对近3月变化比例，如 0.6 表示 60%",
    )

    distinct_in_sources_5d: int | None = Field(
        default=None, description="近5日不同转入来源账户数"
    )
    outbound_amount_5d: Decimal | None = Field(
        default=None, description="近5日转出金额合计"
    )
    outbound_concentration: float | None = Field(
        default=None, description="转出对手方集中度 0~1"
    )

    has_large_inbound_5d: bool = Field(
        default=False, description="近5日是否有单笔≥10万转入"
    )
    distinct_out_targets_3d: int | None = Field(
        default=None, description="随后3日分散转出对手账户数"
    )
    outbound_below_ctr_threshold: bool = Field(
        default=False,
        description="分散转出单笔是否均低于大额转账报告标准（20万）",
    )

    linked_account_count: int | None = Field(
        default=None, description="证件/手机/设备关联账户数"
    )
    aggregation_amount_7d: Decimal | None = Field(
        default=None, description="7日归集至同一目标金额"
    )
    funds_to_same_target: bool = False

    gambling_inbound_small: bool = Field(
        default=False, description="RW-019① 小额入金特征"
    )
    gambling_outbound_large_integer: bool = Field(
        default=False, description="RW-019② 大额整数出金特征"
    )
    gambling_inbound_night: bool = Field(
        default=False, description="RW-019③ 20:00-02:00 入金集中"
    )

    force_audit: bool = Field(
        default=False,
        description="无命中时强制写「已检-无风险」审计样例（演示用）",
    )
    extra: dict[str, Any] = Field(default_factory=dict)


class HitRuleItem(PublicSchema):
    rule_id: str
    rule_name: str
    severity: str
    detail: str


class MonitorResponse(PublicSchema):
    customer_id: str
    hit: bool
    alert_level: str | None = None
    hit_rules: list[HitRuleItem] = Field(default_factory=list)
    reason: str | None = None
    confidence: float = Field(ge=0, le=1)
    skip_full: bool = False
    alert_id: int | None = None
    llm_review: str | None = None
    llm_source: str | None = None
    record_type: str | None = None
    status: str | None = None
    work_order_id: str | None = None
    broadcasted: bool = False
    redis_published: bool = Field(
        default=False,
        description="是否成功 PUBLISH 到 Redis（内存总线成功不等于 Redis 成功）",
    )
    redis_error: str | None = Field(
        default=None,
        description="Redis 发布失败原因（若有）",
    )


class HandleAlertRequest(PublicSchema):
    status: Literal["未处理", "已确认", "已排除"]


class AlertView(PublicSchema):
    alert_id: int
    customer_id: str
    record_type: str
    alert_level: str | None = None
    hit_rules: list[Any] = Field(default_factory=list)
    reason: str | None = None
    confidence: float
    llm_review: str | None = None
    status: str
    work_order_id: str | None = None
    broadcasted: bool
    created_at: str
