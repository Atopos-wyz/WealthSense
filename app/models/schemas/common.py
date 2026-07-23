"""API 公共模型。"""

from enum import StrEnum
from decimal import Decimal

from pydantic import field_serializer

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
