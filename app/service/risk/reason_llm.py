"""LLM 原因生成与二次复核（不改 alert_level；失败模板兜底）。

定稿：
- llm_review 仅三值：同意规则 / 建议人工复核 / 可疑；失败为 null
- 冲突用 llm_conflict 布尔；规则级别权威，禁止改级
- 供应商不写死；由风控隔离配置注入 base_url / api_key / model
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.tool.risk.base import RuleHit
from app.utils.logger import get_logger

logger = get_logger(__name__)

LLM_REVIEW_AGREE = "同意规则"
LLM_REVIEW_HUMAN = "建议人工复核"
LLM_REVIEW_SUSPICIOUS = "可疑"
ALLOWED_LLM_REVIEWS = frozenset(
    {LLM_REVIEW_AGREE, LLM_REVIEW_HUMAN, LLM_REVIEW_SUSPICIOUS}
)


@dataclass(frozen=True, slots=True)
class LlmEnrichment:
    reason: str
    llm_review: str | None
    confidence: float
    source: str  # mock | http | template
    llm_conflict: bool = False


def _template_reason(hits: list[RuleHit]) -> str:
    return "；".join(
        f"触发规则 {hit.rule_id}（{hit.rule_name}）：{hit.detail}" for hit in hits
    )


def _ensure_rule_ids_in_reason(reason: str, hits: list[RuleHit]) -> str:
    for hit in hits:
        if hit.rule_id not in reason:
            return _template_reason(hits)
    return reason


def _normalize_review(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if text in ALLOWED_LLM_REVIEWS:
        return text
    # 兼容旧 mock / 模型别名
    aliases = {
        "正常倾向": LLM_REVIEW_AGREE,
        "同意": LLM_REVIEW_AGREE,
        "人工复核": LLM_REVIEW_HUMAN,
        "建议复核": LLM_REVIEW_HUMAN,
        "未知": None,
        "未启用": None,
        "信息不足": None,
    }
    return aliases.get(text, None)


def _mock_review(alert_level: str, hits: list[RuleHit]) -> str:
    if alert_level == "高" and len(hits) >= 2:
        return LLM_REVIEW_SUSPICIOUS
    if alert_level in {"高", "中"}:
        return LLM_REVIEW_HUMAN
    return LLM_REVIEW_AGREE


def _adjust_confidence(base: float, review: str | None) -> float:
    if review == LLM_REVIEW_AGREE:
        return round(max(0.0, base - 0.02), 2)
    if review == LLM_REVIEW_SUSPICIOUS:
        return round(min(0.99, base + 0.05), 2)
    return base


def _detect_conflict(
    *,
    alert_level: str,
    llm_review: str | None,
    model_says_no_risk: bool = False,
) -> tuple[str | None, bool]:
    """规则优先：冲突时仍保留规则级别，标记 conflict 并倾向人工复核。"""

    if model_says_no_risk and alert_level in {"中", "高"}:
        return LLM_REVIEW_HUMAN, True
    return llm_review, False


class ReasonLlmService:
    """
    mode=mock：本地可演示，不依赖外部 API。
    mode=http：按隔离配置调用外部 Chat Completions；失败模板兜底。
    mode=off：仅模板，llm_review=null。
    永不修改规则给出的 alert_level。
    """

    def __init__(
        self,
        mode: str = "mock",
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._mode = mode
        self._base_url = (base_url or "").rstrip("/") or None
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_seconds

    @classmethod
    def from_settings(cls, settings: Any, *, mode: str | None = None) -> ReasonLlmService:
        """从 Settings 读取风控隔离 LLM 配置；缺省回退通用 llm_*。"""

        risk_mode = mode or getattr(settings, "risk_llm_mode", None) or "mock"
        base_url = getattr(settings, "risk_llm_base_url", None) or getattr(
            settings, "llm_base_url", None
        )
        api_key_obj = getattr(settings, "risk_llm_api_key", None) or getattr(
            settings, "llm_api_key", None
        )
        api_key = None
        if api_key_obj is not None:
            api_key = (
                api_key_obj.get_secret_value()
                if hasattr(api_key_obj, "get_secret_value")
                else str(api_key_obj)
            )
        model = getattr(settings, "risk_llm_model", None) or getattr(
            settings, "llm_model", None
        )
        timeout = float(
            getattr(settings, "risk_llm_timeout_seconds", None)
            or getattr(settings, "llm_timeout_seconds", 10)
        )
        if risk_mode == "http" and not (base_url and api_key and model):
            logger.warning("风控 LLM http 模式缺配置，回退 mock")
            risk_mode = "mock"
        return cls(
            mode=risk_mode,
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout_seconds=timeout,
        )

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
                llm_review=None,
                confidence=confidence,
                source="template",
                llm_conflict=False,
            )

        template = _template_reason(hits)
        if self._mode == "off":
            return LlmEnrichment(
                reason=template,
                llm_review=None,
                confidence=confidence,
                source="template",
                llm_conflict=False,
            )

        if self._mode == "http":
            try:
                return await self._http_enrich(hits, alert_level, confidence)
            except Exception as exc:
                logger.warning("风控 LLM HTTP 失败，模板兜底: %s", exc, exc_info=True)
                return LlmEnrichment(
                    reason=template,
                    llm_review=None,
                    confidence=confidence,
                    source="template",
                    llm_conflict=False,
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
        reason = _ensure_rule_ids_in_reason(reason, hits)
        review = _mock_review(alert_level, hits)
        review, conflict = _detect_conflict(
            alert_level=alert_level, llm_review=review
        )
        return LlmEnrichment(
            reason=reason,
            llm_review=review,
            confidence=_adjust_confidence(confidence, review),
            source=source,
            llm_conflict=conflict,
        )

    async def _http_enrich(
        self,
        hits: list[RuleHit],
        alert_level: str,
        confidence: float,
    ) -> LlmEnrichment:
        import httpx

        if not (self._base_url and self._api_key and self._model):
            raise RuntimeError("风控 LLM http 配置不完整")

        rule_block = "\n".join(
            f"- {h.rule_id} {h.rule_name}: {h.detail}" for h in hits
        )
        system = (
            "你是反洗钱风控复核助手。规则引擎已给出级别与命中规则。"
            "你只能解释与标记，禁止改级别、禁止增删规则。"
            "只输出 JSON："
            '{"llm_review":"同意规则|建议人工复核|可疑",'
            '"reason":"中文摘要含全部 rule_id",'
            '"disagree_with_rules":false}'
        )
        user = (
            f"规则级别: {alert_level}\n命中规则:\n{rule_block}\n"
            "若你认为证据不足以支持该级别，将 disagree_with_rules 设为 true，"
            "llm_review 用「建议人工复核」。"
        )
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self._model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()

        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        parsed = _parse_llm_json(content)
        review = _normalize_review(parsed.get("llm_review"))
        reason = str(parsed.get("reason") or "").strip() or _template_reason(hits)
        reason = _ensure_rule_ids_in_reason(reason, hits)
        disagree = bool(parsed.get("disagree_with_rules"))
        review, conflict = _detect_conflict(
            alert_level=alert_level,
            llm_review=review or LLM_REVIEW_HUMAN,
            model_says_no_risk=disagree,
        )
        return LlmEnrichment(
            reason=reason,
            llm_review=review,
            confidence=_adjust_confidence(confidence, review),
            source="http",
            llm_conflict=conflict,
        )


def _parse_llm_json(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines if not line.strip().startswith("```")
        )
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start : end + 1])
                return data if isinstance(data, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}
