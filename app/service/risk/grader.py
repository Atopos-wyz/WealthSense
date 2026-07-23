"""级别就高 + 轻量置信度。"""

from __future__ import annotations

from app.tool.risk.base import RuleHit, max_alert_level


def grade_alert_level(hits: list[RuleHit]) -> str | None:
    return max_alert_level([hit.alert_level for hit in hits])


def compute_confidence(*, hits: list[RuleHit], skip_full: bool) -> float:
    """
    轻量置信度（非 ML）：
    - 无命中且浅检跳过：偏高，表示「像正常交易」
    - 无命中但已全量：略低一点，表示检查更充分后的干净结论
    - 有命中：随命中数与规则权重上升（对「确有风险信号」的置信）
    """
    if not hits:
        return 0.90 if skip_full else 0.85

    weight_sum = sum(hit.weight for hit in hits)
    score = 0.55 + 0.12 * len(hits) + 0.08 * weight_sum
    return round(min(score, 0.99), 2)
