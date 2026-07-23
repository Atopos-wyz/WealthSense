"""风险评估接口模型。"""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models.schemas.common import DecimalJsonModel, RiskLevel


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
