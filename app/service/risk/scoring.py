"""风险问卷计分规则。"""

from decimal import Decimal, ROUND_HALF_UP

from app.models.schemas.common import RiskLevel
from app.models.schemas.risk import RiskAnswer, ScoredAnswer
from app.service.risk.questionnaire import QUESTIONS
from app.utils.exceptions import BusinessError


RISK_LABELS: dict[RiskLevel, str] = {
    RiskLevel.C1: "保守型",
    RiskLevel.C2: "稳健型",
    RiskLevel.C3: "平衡型",
    RiskLevel.C4: "进取型",
    RiskLevel.C5: "激进型",
}


def map_score_to_level(score: Decimal) -> RiskLevel:
    if score <= 20:
        return RiskLevel.C1
    if score <= 40:
        return RiskLevel.C2
    if score <= 60:
        return RiskLevel.C3
    if score <= 80:
        return RiskLevel.C4
    return RiskLevel.C5


def conservative_merge(
    official_level: RiskLevel,
    model_level: RiskLevel,
) -> RiskLevel:
    return RiskLevel(f"C{min(int(official_level[1]), int(model_level[1]))}")


def score_answers(
    answers: list[RiskAnswer],
) -> tuple[Decimal, RiskLevel, list[ScoredAnswer]]:
    expected_ids = {question.id for question in QUESTIONS}
    actual_ids = {answer.q for answer in answers}
    if actual_ids != expected_ids or len(answers) != len(QUESTIONS):
        missing = sorted(expected_ids - actual_ids)
        extra = sorted(actual_ids - expected_ids)
        detail = []
        if missing:
            detail.append(f"缺少题目: {missing}")
        if extra:
            detail.append(f"未知题目: {extra}")
        raise BusinessError(
            code=400,
            message="必须完整回答16道题" + (f"（{'；'.join(detail)}）" if detail else ""),
        )

    question_map = {question.id: question for question in QUESTIONS}
    scored_answers: list[ScoredAnswer] = []
    for answer in sorted(answers, key=lambda item: item.q):
        option_map = {
            option.code: option.score
            for option in question_map[answer.q].options
        }
        score = option_map[answer.a]
        scored_answers.append(
            ScoredAnswer(q=answer.q, a=answer.a, score=score)
        )

    total_score = (
        sum((item.score for item in scored_answers), Decimal("0"))
        / Decimal(len(QUESTIONS))
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return total_score, map_score_to_level(total_score), scored_answers
