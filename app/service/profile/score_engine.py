"""客户画像四维评分与硬性门槛。"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from app.models.schemas.common import RiskLevel
from app.models.schemas.profile import (
    EducationLevel,
    OccupationType,
    ProfileFacts,
    TradingFrequency,
)
from app.service.risk.scoring import conservative_merge, map_score_to_level


RULE_VERSION = "PROFILE-2026.1"


@dataclass(frozen=True)
class ProfileScore:
    d1: Decimal
    d2: Decimal
    d3: Decimal
    d4: Decimal
    total: Decimal
    official_level: RiskLevel
    model_level: RiskLevel
    effective_level: RiskLevel
    score_detail: dict


def _decimal(value: float | int | str) -> Decimal:
    return Decimal(str(value))


def _round(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _age_score(age: int) -> int:
    if age < 18 or age > 80:
        return 0
    if age <= 25:
        return 4
    if age <= 40:
        return 8
    if age <= 60:
        return 10
    if age <= 70:
        return 7
    return 4


def _income_score(income: Decimal) -> int:
    if income == 0:
        return 0
    if income < 50_000:
        return 2
    if income < 100_000:
        return 4
    if income < 300_000:
        return 6
    if income < 500_000:
        return 8
    return 10


def _asset_score(assets: Decimal) -> int:
    if assets < 10_000:
        return 1
    if assets < 100_000:
        return 3
    if assets < 500_000:
        return 5
    if assets < 1_000_000:
        return 7
    if assets < 5_000_000:
        return 9
    return 10


def _experience_year_score(years: int) -> int:
    if years == 0:
        return 0
    if years < 3:
        return 4
    if years < 5:
        return 6
    if years < 10:
        return 8
    return 10


def _historical_return_score(rate: Decimal | None) -> int:
    if rate is None:
        return 2
    if rate < 0:
        return 3
    if rate < 5:
        return 5
    if rate < 15:
        return 8
    return 10


def evaluate_profile(
    facts: ProfileFacts,
    official_level: RiskLevel,
    questionnaire_score: Decimal,
) -> ProfileScore:
    education_scores = {
        EducationLevel.JUNIOR_OR_BELOW: 2,
        EducationLevel.HIGH_SCHOOL: 4,
        EducationLevel.ASSOCIATE: 6,
        EducationLevel.BACHELOR: 8,
        EducationLevel.MASTER_OR_ABOVE: 10,
    }
    occupation_scores = {
        OccupationType.UNEMPLOYED: 0,
        OccupationType.STUDENT: 2,
        OccupationType.FREELANCER: 5,
        OccupationType.EMPLOYEE: 7,
        OccupationType.PROFESSIONAL: 8,
        OccupationType.MANAGEMENT: 10,
        OccupationType.PUBLIC_SECTOR: 8,
    }
    d1_items = {
        "age": _age_score(facts.age),
        "education": education_scores[facts.education],
        "occupation": occupation_scores[facts.occupation],
        "annual_income": _income_score(facts.annual_income),
        "investable_assets": _asset_score(facts.investable_assets),
    }
    d1 = _round(
        sum((_decimal(value) for value in d1_items.values()), Decimal("0"))
        / Decimal("5")
        / Decimal("10")
        * Decimal("25")
    )

    frequency_scores = {
        TradingFrequency.NONE: 0,
        TradingFrequency.LOW: 4,
        TradingFrequency.MEDIUM: 7,
        TradingFrequency.HIGH: 10,
    }
    d2_items = {
        "investment_years": _experience_year_score(facts.investment_years),
        "product_types": min(len(set(facts.experienced_product_types)) * 2, 10),
        "trading_frequency": frequency_scores[facts.trading_frequency],
        "historical_return": _historical_return_score(
            facts.historical_return_rate
        ),
    }
    d2 = _round(
        sum((_decimal(value) for value in d2_items.values()), Decimal("0"))
        / Decimal("4")
        / Decimal("10")
        * Decimal("25")
    )

    loss_adjustments = {
        "A": Decimal("0"),
        "B": Decimal("1.67"),
        "C": Decimal("3.33"),
        "D": Decimal("5"),
    }
    d3_base = questionnaire_score / Decimal("100") * Decimal("25")
    d3 = _round(
        min(
            Decimal("30"),
            max(Decimal("0"), d3_base + loss_adjustments[facts.loss_tolerance]),
        )
    )
    d4 = Decimal("0") if facts.has_confirmed_active_high_risk else Decimal("20")
    total = _round(d1 + d2 + d3 + d4)
    model_level = map_score_to_level(total)
    effective_level = conservative_merge(official_level, model_level)

    manual_review = facts.age < 18 or facts.age > 80
    low_capacity_restriction = (
        facts.annual_income == 0 and facts.investable_assets < 10_000
    )
    restrictions = {
        "manual_review_required": manual_review,
        "maximum_product_risk": (
            "R2"
            if low_capacity_restriction
            else f"R{int(effective_level[1])}"
        ),
        "reasons": [
            reason
            for condition, reason in (
                (manual_review, "年龄不在18—80岁范围内"),
                (low_capacity_restriction, "无收入且可投资资产低于1万元"),
            )
            if condition
        ],
    }
    return ProfileScore(
        d1=d1,
        d2=d2,
        d3=d3,
        d4=d4,
        total=total,
        official_level=official_level,
        model_level=model_level,
        effective_level=effective_level,
        score_detail={
            "d1_items": d1_items,
            "d2_items": d2_items,
            "d3": {
                "questionnaire_score": str(questionnaire_score),
                "base_score": str(_round(d3_base)),
                "loss_tolerance": facts.loss_tolerance,
                "loss_adjustment": str(loss_adjustments[facts.loss_tolerance]),
            },
            "d4": {
                "confirmed_active_high_risk": (
                    facts.has_confirmed_active_high_risk
                ),
                "rule": "确认且有效的高风险事件D4=0，否则D4=20",
            },
            "restrictions": restrictions,
        },
    )


def investment_experience_range(years: int) -> str:
    if years < 1:
        return "0-1年"
    if years < 3:
        return "1-3年"
    if years < 5:
        return "3-5年"
    if years < 10:
        return "5-10年"
    return "10年以上"


def annual_income_range(income: Decimal) -> str:
    if income < 50_000:
        return "5万元以下"
    if income < 100_000:
        return "5-10万元"
    if income < 300_000:
        return "10-30万元"
    if income < 500_000:
        return "30-50万元"
    return "50万元以上"
