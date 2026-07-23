"""LLM-backed intent recognition with deterministic fallback."""

from __future__ import annotations

import json
import logging
from time import perf_counter
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.agent.operator.intent_classifier import classify_intent
from app.models.schemas.common import OperationIntent

logger = logging.getLogger(__name__)


class IntentRecognition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: OperationIntent
    confidence: float = Field(ge=0, le=1)
    params: dict[str, Any] = Field(default_factory=dict)
    source: str = "llm"
    fallback_reason: str | None = None
    latency_ms: int = Field(default=0, ge=0)


class IntentRecognizer(Protocol):
    async def recognize(
        self,
        message: str,
        known_params: dict[str, Any],
    ) -> IntentRecognition: ...


class KeywordIntentRecognizer:
    async def recognize(
        self,
        message: str,
        known_params: dict[str, Any],
    ) -> IntentRecognition:
        del known_params
        return IntentRecognition(
            intent=classify_intent(message),
            confidence=1,
            source="keyword_fallback",
        )


SYSTEM_PROMPT = """你是金融业务操作意图分类器。
只能从以下意图中选择一个：
purchase, redeem, transfer, risk_reassessment, update_profile,
product_query, suspicious_report, create_work_order, unknown。

同时提取用户明确表达的业务参数。不得猜测、补造或执行任何操作。
只返回 JSON，不要返回 Markdown：
{"intent":"枚举值","confidence":0到1之间的小数,"params":{}}

参数提示：
purchase: customer_id, product_id, account_id, amount, currency
redeem: customer_id, holding_id, redeem_type(all或partial), shares
transfer: customer_id, from_account_id, to_account_id, amount, currency
risk_reassessment: customer_id, questionnaire_version, answers
update_profile: customer_id, field_name(phone/address/email), new_value
product_query: product_id, fields
suspicious_report: customer_id, transaction_id, reason, evidence_refs
create_work_order: customer_id, work_order_type, description, priority

若不是上述业务操作，intent 必须为 unknown。"""


class OpenAICompatibleIntentRecognizer:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.url = f"{base_url.rstrip('/')}/chat/completions"
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.client = client

    async def recognize(
        self,
        message: str,
        known_params: dict[str, Any],
    ) -> IntentRecognition:
        del known_params
        started_at = perf_counter()
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"message": message},
                        ensure_ascii=False,
                    ),
                },
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.client is not None:
            response = await self.client.post(
                self.url,
                json=payload,
                headers=headers,
                timeout=self.timeout_seconds,
            )
        else:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.url,
                    json=payload,
                    headers=headers,
                    timeout=self.timeout_seconds,
                )
        response.raise_for_status()
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        candidate = IntentRecognition.model_validate_json(content)
        candidate.latency_ms = round((perf_counter() - started_at) * 1000)
        return candidate


class HybridIntentRecognizer:
    def __init__(
        self,
        llm: IntentRecognizer | None,
        *,
        confidence_threshold: float,
        fallback: IntentRecognizer | None = None,
    ) -> None:
        self.llm = llm
        self.confidence_threshold = confidence_threshold
        self.fallback = fallback or KeywordIntentRecognizer()

    async def recognize(
        self,
        message: str,
        known_params: dict[str, Any],
    ) -> IntentRecognition:
        if self.llm is None:
            return await self._fallback(message, known_params, "llm_not_configured")
        try:
            result = await self.llm.recognize(message, known_params)
        except Exception as exc:
            logger.warning(
                "LLM intent recognition failed; using keyword fallback: %s",
                type(exc).__name__,
            )
            return await self._fallback(
                message,
                known_params,
                f"llm_error:{type(exc).__name__}",
            )
        if result.confidence < self.confidence_threshold:
            return await self._fallback(
                message,
                known_params,
                "confidence_below_threshold",
            )
        if result.intent == OperationIntent.UNKNOWN:
            return await self._fallback(
                message,
                known_params,
                "llm_returned_unknown",
            )
        return result

    async def _fallback(
        self,
        message: str,
        known_params: dict[str, Any],
        reason: str,
    ) -> IntentRecognition:
        result = await self.fallback.recognize(message, known_params)
        result.source = "keyword_fallback"
        result.fallback_reason = reason
        return result
