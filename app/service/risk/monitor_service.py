"""监测编排：门控 → 分级/置信度 → LLM → 落库 → 中高广播。"""

from __future__ import annotations

import random
from typing import Any

from app.dao.mysql.risk_alert_dao import InMemoryRiskAlertStore, RiskAlertStore
from app.event.payloads import RiskAlertEvent
from app.event.risk_alert_publisher import (
    CompositeEventPublisher,
    InMemoryEventPublisher,
    RiskAlertPublisher,
)
from app.models.entities.risk_alert import RiskAlertRecord
from app.models.schemas.risk import HitRuleItem, MonitorRequest, MonitorResponse
from app.service.risk.access_policy import scrub_extra
from app.service.risk.alert_service import RiskAlertService
from app.service.risk.engine import RiskRuleEngine
from app.service.risk.grader import compute_confidence, grade_alert_level
from app.service.risk.reason_llm import ReasonLlmService
from app.tool.risk.base import RuleHit
from app.tool.risk.context import TransactionContext

_BROADCAST_LEVELS = frozenset({"中", "高"})


def _to_context(request: MonitorRequest) -> TransactionContext:
    return TransactionContext(
        customer_id=request.customer_id,
        amount=request.amount,
        currency=request.currency,
        counterparty_country=request.counterparty_country,
        trade_type=request.trade_type,
        is_pep=request.is_pep,
        is_pep_related=request.is_pep_related,
        has_new_overseas_counterparty=request.has_new_overseas_counterparty,
        pattern_change_ratio=request.pattern_change_ratio,
        distinct_in_sources_5d=request.distinct_in_sources_5d,
        outbound_amount_5d=request.outbound_amount_5d,
        outbound_concentration=request.outbound_concentration,
        has_large_inbound_5d=request.has_large_inbound_5d,
        distinct_out_targets_3d=request.distinct_out_targets_3d,
        outbound_below_ctr_threshold=request.outbound_below_ctr_threshold,
        linked_account_count=request.linked_account_count,
        aggregation_amount_7d=request.aggregation_amount_7d,
        funds_to_same_target=request.funds_to_same_target,
        gambling_inbound_small=request.gambling_inbound_small,
        gambling_outbound_large_integer=request.gambling_outbound_large_integer,
        gambling_inbound_night=request.gambling_inbound_night,
        extra=scrub_extra(request.extra),
    )


def _hit_items(hits: list[RuleHit]) -> list[HitRuleItem]:
    return [
        HitRuleItem(
            rule_id=hit.rule_id,
            rule_name=hit.rule_name,
            severity=hit.severity.value,
            detail=hit.detail,
        )
        for hit in hits
    ]


def _hit_dicts(hits: list[RuleHit]) -> list[dict[str, Any]]:
    return [
        {
            "rule_id": hit.rule_id,
            "rule_name": hit.rule_name,
            "severity": hit.severity.value,
            "detail": hit.detail,
        }
        for hit in hits
    ]


class RiskMonitorService:
    def __init__(
        self,
        engine: RiskRuleEngine | None = None,
        *,
        store: RiskAlertStore | None = None,
        publisher: RiskAlertPublisher | None = None,
        llm: ReasonLlmService | None = None,
        audit_sample_rate: float = 0.0,
        memory_publisher: InMemoryEventPublisher | None = None,
    ) -> None:
        self._engine = engine or RiskRuleEngine()
        self._store = store or InMemoryRiskAlertStore()
        self._alert_service = RiskAlertService(self._store)
        self._memory_publisher = memory_publisher or InMemoryEventPublisher()
        self._publisher = publisher or self._memory_publisher
        self._llm = llm or ReasonLlmService(mode="mock")
        self._audit_sample_rate = max(0.0, min(1.0, audit_sample_rate))

    @property
    def store(self) -> RiskAlertStore:
        return self._store

    @property
    def memory_publisher(self) -> InMemoryEventPublisher:
        return self._memory_publisher

    @property
    def publisher(self) -> RiskAlertPublisher:
        return self._publisher

    async def monitor(self, request: MonitorRequest) -> MonitorResponse:
        context = _to_context(request)
        engine_result = self._engine.evaluate_with_gate(context)
        hits = engine_result.hits
        confidence = compute_confidence(hits=hits, skip_full=engine_result.skip_full)

        if not hits:
            return await self._handle_no_hit(
                request=request,
                confidence=confidence,
                skip_full=engine_result.skip_full,
            )

        alert_level = grade_alert_level(hits) or "低"
        enrichment = await self._llm.enrich(
            hits=hits,
            alert_level=alert_level,
            confidence=confidence,
        )

        record = RiskAlertRecord(
            id=0,
            customer_id=request.customer_id,
            record_type="alert",
            alert_level=alert_level,
            hit_rules=_hit_dicts(hits),
            reason=enrichment.reason,
            confidence=enrichment.confidence,
            llm_review=enrichment.llm_review,
            llm_conflict=enrichment.llm_conflict,
            status="未处理",
        )
        saved = await self._alert_service.save(record)

        broadcasted = False
        redis_published = False
        redis_error: str | None = None
        if alert_level in _BROADCAST_LEVELS:
            event = RiskAlertEvent(
                alert_id=saved.id,
                customer_id=saved.customer_id,
                alert_level=alert_level,
                trigger_rules=[hit.rule_id for hit in hits],
                confidence=enrichment.confidence,
                llm_review=enrichment.llm_review,
                llm_conflict=saved.llm_conflict,
                reason_summary=(enrichment.reason or "")[:200],
                work_order_id=saved.work_order_id,
            )
            redis_published = bool(await self._publisher.publish_risk_alert(event))
            if isinstance(self._publisher, CompositeEventPublisher):
                redis_error = self._publisher.last_redis_error
            await self._alert_service.mark_broadcasted(saved.id)
            broadcasted = True
            saved.broadcasted = True

        return MonitorResponse(
            customer_id=request.customer_id,
            hit=True,
            alert_level=alert_level,
            hit_rules=_hit_items(hits),
            reason=enrichment.reason,
            confidence=enrichment.confidence,
            skip_full=engine_result.skip_full,
            alert_id=saved.id,
            llm_review=enrichment.llm_review,
            llm_conflict=saved.llm_conflict,
            llm_source=enrichment.source,
            record_type=saved.record_type,
            status=saved.status,
            work_order_id=saved.work_order_id,
            broadcasted=broadcasted,
            redis_published=redis_published,
            redis_error=redis_error,
        )

    async def _handle_no_hit(
        self,
        *,
        request: MonitorRequest,
        confidence: float,
        skip_full: bool,
    ) -> MonitorResponse:
        should_audit = request.force_audit or (
            self._audit_sample_rate > 0
            and random.random() < self._audit_sample_rate
        )
        alert_id = None
        record_type = None
        status = None
        if should_audit:
            saved = await self._alert_service.save(
                RiskAlertRecord(
                    id=0,
                    customer_id=request.customer_id,
                    record_type="audit_clean",
                    alert_level=None,
                    hit_rules=[],
                    reason="已检-无风险",
                    confidence=confidence,
                    llm_review=None,
                    status="已确认",
                )
            )
            alert_id = saved.id
            record_type = saved.record_type
            status = saved.status

        return MonitorResponse(
            customer_id=request.customer_id,
            hit=False,
            alert_level=None,
            hit_rules=[],
            reason=None,
            confidence=confidence,
            skip_full=skip_full,
            alert_id=alert_id,
            llm_review=None,
            llm_conflict=False,
            llm_source=None,
            record_type=record_type,
            status=status,
            work_order_id=None,
            broadcasted=False,
            redis_published=False,
            redis_error=None,
        )
