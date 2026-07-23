"""客户画像接口模型。"""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.schemas.common import DataSource, DecimalJsonModel, RiskLevel


class EducationLevel(StrEnum):
    JUNIOR_OR_BELOW = "JUNIOR_OR_BELOW"
    HIGH_SCHOOL = "HIGH_SCHOOL"
    ASSOCIATE = "ASSOCIATE"
    BACHELOR = "BACHELOR"
    MASTER_OR_ABOVE = "MASTER_OR_ABOVE"


class OccupationType(StrEnum):
    UNEMPLOYED = "UNEMPLOYED"
    STUDENT = "STUDENT"
    FREELANCER = "FREELANCER"
    EMPLOYEE = "EMPLOYEE"
    PROFESSIONAL = "PROFESSIONAL"
    MANAGEMENT = "MANAGEMENT"
    PUBLIC_SECTOR = "PUBLIC_SECTOR"


class TradingFrequency(StrEnum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ProfileFacts(BaseModel):
    age: int = Field(ge=0, le=120)
    education: EducationLevel
    occupation: OccupationType
    annual_income: Decimal = Field(ge=0)
    investable_assets: Decimal = Field(ge=0)
    investment_years: int = Field(ge=0, le=100)
    experienced_product_types: list[str] = Field(default_factory=list)
    trading_frequency: TradingFrequency = TradingFrequency.NONE
    historical_return_rate: Decimal | None = None
    loss_tolerance: Literal["A", "B", "C", "D"]
    has_confirmed_active_high_risk: bool = False


class ProfileCreateRequest(BaseModel):
    customer_id: int = Field(gt=0)
    trigger_type: str = Field(default="MANUAL_CREATE", max_length=32)
    trigger_id: str = Field(min_length=1, max_length=64)
    facts: ProfileFacts
    asset_allocation: dict[str, Decimal] = Field(default_factory=dict)
    product_preference: dict[str, list[str]] = Field(default_factory=dict)
    source: DataSource = DataSource.KYC
    conversation_text: str | None = Field(default=None, max_length=10000)

    @model_validator(mode="after")
    def allocation_must_be_valid(self) -> "ProfileCreateRequest":
        if any(value < 0 for value in self.asset_allocation.values()):
            raise ValueError("资产配置比例不能为负数")
        total = sum(self.asset_allocation.values(), Decimal("0"))
        if total and abs(total - Decimal("100")) > Decimal("0.01"):
            raise ValueError("资产配置比例合计必须为100")
        return self


class ProfileUpdateRequest(BaseModel):
    investment_experience: str | None = Field(default=None, max_length=16)
    annual_income_range: str | None = Field(default=None, max_length=32)
    product_preference: dict[str, list[str]] | None = None
    source: DataSource
    trigger_id: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def at_least_one_field(self) -> "ProfileUpdateRequest":
        if (
            self.investment_experience is None
            and self.annual_income_range is None
            and self.product_preference is None
        ):
            raise ValueError("至少提供一个需要更新的画像字段")
        return self


class ProfileResponse(DecimalJsonModel):
    customer_id: int
    risk_level: RiskLevel | None
    investment_experience: str | None
    annual_income_range: str | None
    total_assets: Decimal | None
    asset_allocation: dict[str, Decimal]
    product_preference: dict[str, list[str]]
    confidence_score: Decimal
    create_time: datetime
    update_time: datetime


class FieldUpdateResult(BaseModel):
    field_name: str
    resolution: Literal["APPLIED", "REJECTED", "CANDIDATE"]
    reason: str


class ProfileUpdateResult(BaseModel):
    profile: ProfileResponse
    fields: list[FieldUpdateResult]


class ProfileEvaluationResponse(DecimalJsonModel):
    evaluation_no: str
    customer_id: int
    d1_score: Decimal
    d2_score: Decimal
    d3_score: Decimal
    d4_score: Decimal
    total_score: Decimal
    official_risk_level: RiskLevel
    model_risk_level: RiskLevel
    effective_risk_level: RiskLevel
    assessment_id: int | None
    score_detail: dict
    rule_version: str
    trigger_type: str
    trigger_id: str
    create_time: datetime
