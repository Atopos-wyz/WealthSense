"""风险问卷及分级规则测试。"""

import unittest
from decimal import Decimal

from app.models.schemas.common import RiskLevel
from app.models.schemas.risk import RiskAnswer, RiskDimension
from app.service.risk.questionnaire import QUESTIONS, get_questionnaire
from app.service.risk.scoring import map_score_to_level, score_answers
from app.utils.exceptions import BusinessError


def answers(option: str) -> list[RiskAnswer]:
    return [
        RiskAnswer(q=question.id, a=option)
        for question in QUESTIONS
    ]


class RiskScoringTest(unittest.TestCase):
    def test_questionnaire_has_16_questions_and_four_options(self) -> None:
        questionnaire = get_questionnaire()

        self.assertEqual(questionnaire.total_questions, 16)
        self.assertEqual(len(questionnaire.questions), 16)
        self.assertEqual(
            {
                question.dimension
                for question in questionnaire.questions
            },
            set(RiskDimension),
        )
        self.assertTrue(
            all(len(question.options) == 4 for question in questionnaire.questions)
        )

    def test_all_a_is_c1_and_all_d_is_c5(self) -> None:
        low_score, low_level, _ = score_answers(answers("A"))
        high_score, high_level, _ = score_answers(answers("D"))

        self.assertEqual(low_score, Decimal("0.00"))
        self.assertEqual(low_level, RiskLevel.C1)
        self.assertEqual(high_score, Decimal("100.00"))
        self.assertEqual(high_level, RiskLevel.C5)

    def test_level_boundaries_match_requirement(self) -> None:
        cases = {
            Decimal("20"): RiskLevel.C1,
            Decimal("20.01"): RiskLevel.C2,
            Decimal("40"): RiskLevel.C2,
            Decimal("40.01"): RiskLevel.C3,
            Decimal("60"): RiskLevel.C3,
            Decimal("60.01"): RiskLevel.C4,
            Decimal("80"): RiskLevel.C4,
            Decimal("80.01"): RiskLevel.C5,
        }

        for score, expected in cases.items():
            with self.subTest(score=score):
                self.assertEqual(map_score_to_level(score), expected)

    def test_incomplete_answers_are_rejected(self) -> None:
        with self.assertRaises(BusinessError) as context:
            score_answers(answers("B")[:-1])

        self.assertIn("必须完整回答16道题", context.exception.message)
