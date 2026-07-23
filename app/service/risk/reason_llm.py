"""LLM 原因生成与二次复核（不改 alert_level；失败模板兜底）。"""

from __future__ import annotations

from dataclasses import dataclass

from app.tool.risk.base import RuleHit


@dataclass(frozen=True, slots=True)
class LlmEnrichment:
    reason: str
    llm_review: str
    confidence: float
    source: str  # mock | http | template


def _template_reason(hits: list[RuleHit]) -> str:
    return "；".join(
        f"触发规则 {hit.rule_id}（{hit.rule_name}）：{hit.detail}" for hit in hits
    )


def _mock_review(alert_level: str, hits: list[RuleHit]) -> str:
    if alert_level == "高" and len(hits) >= 2:
        return "可疑"
    if alert_level == "高":
        return "建议人工复核"
    if alert_level == "中":
        return "建议人工复核"
    return "正常倾向"


def _adjust_confidence(base: float, review: str) -> float:
    if review == "正常倾向":
        return round(max(0.0, base - 0.08), 2)
    if review == "可疑":
        return round(min(0.99, base + 0.05), 2)
    return base


class ReasonLlmService:
    """
    默认 mock 模式：可演示「人话原因 + 复核」且不依赖外部 API。
    http 模式预留；失败一律模板兜底，且永不修改规则给出的 alert_level。
    """

    def __init__(self, mode: str = "mock") -> None:
        self._mode = mode

    async def enrich(
        self,
        *,
        hits: list[RuleHit],
        alert_level: str,
        confidence: float,
    ) -> LlmEnrichment:
        if not hits:
            return LlmEnrichment(
                reason="",
                llm_review="未知",
                confidence=confidence,
                source="template",
            )

        template = _template_reason(hits)
        if self._mode == "off":
            return LlmEnrichment(
                reason=template,
                llm_review="未启用",
                confidence=confidence,
                source="template",
            )

        if self._mode == "http":
            # 阶段 3：外部 HTTP 调用点位预留；当前统一走 mock/模板，保证可演示可降级
            try:
                return await self._mock_enrich(hits, alert_level, confidence, source="http")
            except Exception:
                return LlmEnrichment(
                    reason=template,
                    llm_review="未知",
                    confidence=confidence,
                    source="template",
                )

        return await self._mock_enrich(hits, alert_level, confidence, source="mock")

    async def _mock_enrich(
        self,
        hits: list[RuleHit],
        alert_level: str,
        confidence: float,
        *,
        source: str,
    ) -> LlmEnrichment:
        rule_ids = "、".join(hit.rule_id for hit in hits)
        reason = (
            f"经规则引擎判定触发 {rule_ids}，综合级别为「{alert_level}」。"
            f"摘要：{_template_reason(hits)}"
        )
        # 输出校验：必须包含已命中 rule_id
        for hit in hits:
            if hit.rule_id not in reason:
                reason = f"{reason}（含 {hit.rule_id}）"
        review = _mock_review(alert_level, hits)
        return LlmEnrichment(
            reason=reason,
            llm_review=review,
            confidence=_adjust_confidence(confidence, review),
            source=source,
        )
