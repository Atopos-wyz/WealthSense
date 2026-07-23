"""客户画像四维评分与硬门槛测试。"""

import unittest
from decimal import Decimal

from app.models.schemas.common import RiskLevel
from app.models.schemas.profile import (
    EducationLevel,
    OccupationType,
    ProfileFacts,
    TradingFrequency,
)
from app.service.profile.score_engine import evaluate_profile


def make_facts(**overrides) -> ProfileFacts:
    values = {
        "age": 35,
        "education": EducationLevel.BACHELOR,
        "occupation": OccupationType.EMPLOYEE,
        "annual_income": Decimal("300000"),
        "investable_assets": Decimal("800000"),
        "investment_years": 5,
        "experienced_product_types": ["债券基金", "混合基金"],
        "trading_frequency": TradingFrequency.MEDIUM,
        "historical_return_rate": Decimal("8"),
        "loss_tolerance": "C",
        "has_confirmed_active_high_risk": False,
    }
    values.update(overrides)
    return ProfileFacts(**values)


class ProfileScoreEngineTest(unittest.TestCase):
    def test_only_confirmed_active_high_risk_deducts_d4(self) -> None:
        normal = evaluate_profile(
            make_facts(),
            RiskLevel.C4,
            Decimal("70"),
        )
        high_risk = evaluate_profile(
            make_facts(has_confirmed_active_high_risk=True),
            RiskLevel.C4,
            Decimal("70"),
        )

        self.assertEqual(normal.d4, Decimal("20"))
        self.assertEqual(high_risk.d4, Decimal("0"))
        self.assertEqual(normal.total - high_risk.total, Decimal("20.00"))

    def test_no_income_and_low_assets_limits_products_to_r2(self) -> None:
        result = evaluate_profile(
            make_facts(
                annual_income=Decimal("0"),
                investable_assets=Decimal("9999"),
            ),
            RiskLevel.C3,
            Decimal("50"),
        )

        restrictions = result.score_detail["restrictions"]
        self.assertEqual(restrictions["maximum_product_risk"], "R2")

    def test_age_outside_range_requires_manual_review(self) -> None:
        result = evaluate_profile(
            make_facts(age=17),
            RiskLevel.C2,
            Decimal("30"),
        )

        self.assertTrue(
            result.score_detail["restrictions"]["manual_review_required"]
        )

    def test_effective_level_is_conservative_merge(self) -> None:
        result = evaluate_profile(
            make_facts(),
            RiskLevel.C2,
            Decimal("100"),
        )

        self.assertEqual(result.effective_level, RiskLevel.C2)
