"""投顾 Agent 主编排：画像、意图、领域服务和 Redis 事件。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.advisor.intent_router import classify_intent
from app.config.cache import get_redis_client
from app.dao.mysql.profile_dao import ProfileDAO
from app.dao.mysql.risk_assessment_dao import RiskAssessmentDAO
from app.dao.redis.profile_cache_dao import ProfileCacheDAO
from app.event.publisher import RedisEventPublisher
from app.models.schemas.advisor import (
    AdvisorChatRequest,
    AdvisorChatResponse,
    AdvisorIntent,
    AdvisorRoute,
)
from app.models.schemas.event import (
    AgentEvent,
    AgentEventType,
    AgentType,
    EventPublishReceipt,
)
from app.service.advisor import AdvisorService
from app.utils.logger import get_trace_id


class AdvisorAgent:
    def __init__(
        self,
        session: AsyncSession,
        *,
        publisher: RedisEventPublisher | None = None,
        service: AdvisorService | None = None,
        profile_dao: ProfileDAO | None = None,
        assessment_dao: RiskAssessmentDAO | None = None,
        profile_cache: ProfileCacheDAO | None = None,
    ) -> None:
        self.session = session
        self.publisher = publisher or RedisEventPublisher()
        self.service = service or AdvisorService(session)
        self.profile_dao = profile_dao or ProfileDAO(session)
        self.assessment_dao = assessment_dao or RiskAssessmentDAO(session)
        self.profile_cache = profile_cache or ProfileCacheDAO(
            get_redis_client()
        )

    async def chat(
        self,
        request: AdvisorChatRequest,
    ) -> AdvisorChatResponse:
        trace_id = get_trace_id()
        requested = self._event(
            request,
            event_type=AgentEventType.ADVISOR_REQUESTED,
            source=AgentType.CUSTOMER,
            targets=[AgentType.ADVISOR],
            trace_id=trace_id,
            payload={
                "message": request.message,
                "intent_hint": (
                    request.intent_hint.value
                    if request.intent_hint is not None
                    else None
                ),
                "product_ids": request.product_ids,
                "comparison_customer_ids": (
                    request.comparison_customer_ids
                ),
            },
        )
        receipts = [await self.publisher.publish(requested)]
        try:
            profile = await self._get_profile(request.customer_id)
            if profile is None:
                return await self._assessment_required(
                    request,
                    trace_id=trace_id,
                    requested_event=requested,
                    receipts=receipts,
                    reason="客户画像不存在",
                    profile_found=False,
                )

            assessment = await self.assessment_dao.get_latest(
                request.customer_id,
                valid_only=True,
            )
            if assessment is None or profile.get("risk_level") is None:
                return await self._assessment_required(
                    request,
                    trace_id=trace_id,
                    requested_event=requested,
                    receipts=receipts,
                    reason="风险测评不存在、已失效或画像缺少风险等级",
                    profile_found=True,
                )

            intent = classify_intent(request)
            response = await self._execute(
                request,
                profile,
                intent,
                trace_id,
            )
            response.event_delivery.extend(receipts)
            completed = self._event(
                request,
                event_type=AgentEventType.ADVISOR_COMPLETED,
                source=AgentType.ADVISOR,
                targets=[AgentType.CUSTOMER],
                trace_id=trace_id,
                causation_id=requested.event_id,
                payload={
                    "intent": intent.value,
                    "route": response.route.value,
                    "recommendation_count": len(response.recommendations),
                },
            )
            response.event_delivery.append(
                await self.publisher.publish(completed)
            )
            return response
        except Exception as exc:
            failed = self._event(
                request,
                event_type=AgentEventType.ADVISOR_FAILED,
                source=AgentType.ADVISOR,
                targets=[AgentType.SYSTEM],
                trace_id=trace_id,
                causation_id=requested.event_id,
                payload={"error_type": type(exc).__name__},
            )
            await self.publisher.publish(failed)
            raise

    async def _execute(
        self,
        request: AdvisorChatRequest,
        profile: dict[str, Any],
        intent: AdvisorIntent,
        trace_id: str,
    ) -> AdvisorChatResponse:
        base = {
            "session_id": request.session_id,
            "intent": intent,
            "profile_found": True,
        }
        if intent == AdvisorIntent.PRODUCT_RECOMMENDATION:
            recommendations, reasoning = (
                await self.service.recommend_products(
                    customer_id=request.customer_id,
                    profile=profile,
                    top_k=request.top_k,
                    trace_id=trace_id,
                )
            )
            reply = (
                f"已按 {profile['risk_level']} 风险等级完成适当性过滤，"
                f"为你筛选出 {len(recommendations)} 个候选产品。"
                if recommendations
                else "当前没有找到符合客户风险等级的在售产品。"
            )
            return AdvisorChatResponse(
                **base,
                reply=reply,
                recommendations=recommendations,
                reasoning=reasoning,
            )

        if intent == AdvisorIntent.HOLDING_ANALYSIS:
            analysis, reasoning = await self.service.analyze_holdings(
                customer_id=request.customer_id,
                customer_risk_level=str(profile["risk_level"]),
            )
            return AdvisorChatResponse(
                **base,
                reply=(
                    f"已分析 {analysis.holding_count} 笔有效持仓，"
                    f"识别出 {len(analysis.warnings)} 条风险提示。"
                ),
                holding_analysis=analysis,
                reasoning=reasoning,
            )

        if intent == AdvisorIntent.ASSET_ALLOCATION:
            advice, reasoning = self.service.allocate_assets(profile)
            return AdvisorChatResponse(
                **base,
                reply=(
                    f"已基于 {profile['risk_level']} 风险画像生成"
                    "资产配置比例和调仓建议。"
                ),
                allocation_advice=advice,
                reasoning=reasoning,
            )

        if intent == AdvisorIntent.PRODUCT_COMPARISON:
            customer_ids = list(
                dict.fromkeys(
                    [
                        request.customer_id,
                        *request.comparison_customer_ids,
                    ]
                )
            )
            report, reasoning = await self.service.compare(
                product_ids=request.product_ids,
                customer_ids=customer_ids,
            )
            return AdvisorChatResponse(
                **base,
                reply=report.conclusion,
                comparison_report=report,
                reasoning=reasoning,
            )

        return AdvisorChatResponse(
            **base,
            reply=(
                "我可以处理产品推荐、持仓分析、资产配置和产品/客户对比。"
                "请补充你希望分析的方向。"
            ),
            reasoning=["当前输入未命中四类投顾意图，未执行投资计算"],
        )

    async def _assessment_required(
        self,
        request: AdvisorChatRequest,
        *,
        trace_id: str,
        requested_event: AgentEvent,
        receipts: list[EventPublishReceipt],
        reason: str,
        profile_found: bool,
    ) -> AdvisorChatResponse:
        events: list[AgentEvent] = []
        causation_id = requested_event.event_id
        if not profile_found:
            profile_missing = self._event(
                request,
                event_type=AgentEventType.PROFILE_MISSING,
                source=AgentType.ADVISOR,
                targets=[AgentType.CUSTOMER, AgentType.RISK],
                trace_id=trace_id,
                causation_id=requested_event.event_id,
                payload={
                    "reason": reason,
                    "profile_found": profile_found,
                },
            )
            events.append(profile_missing)
            causation_id = profile_missing.event_id
        assessment_required = self._event(
            request,
            event_type=AgentEventType.ASSESSMENT_REQUIRED,
            source=AgentType.ADVISOR,
            targets=[AgentType.RISK],
            trace_id=trace_id,
            causation_id=causation_id,
            payload={
                "reason": reason,
                "callback_event": AgentEventType.ASSESSMENT_COMPLETED.value,
                "requested_action": "START_RISK_ASSESSMENT",
            },
        )
        events.append(assessment_required)
        receipts.extend(await self.publisher.publish_many(events))
        return AdvisorChatResponse(
            reply=(
                f"{reason}，暂不能生成投资建议。"
                "已通知风险评估模块，请先完成风险测评和客户画像。"
            ),
            session_id=request.session_id,
            intent=AdvisorIntent.RISK_ASSESSMENT_REQUIRED,
            route=AdvisorRoute.RISK_AGENT,
            profile_found=profile_found,
            reasoning=[
                "投顾建议必须基于有效客户画像",
                "缺少有效风险等级时停止推荐并路由到 Risk Agent",
            ],
            event_delivery=receipts,
        )

    async def _get_profile(
        self,
        customer_id: int,
    ) -> dict[str, Any] | None:
        cached = await self.profile_cache.get(customer_id)
        if cached is not None:
            return cached
        profile = await self.profile_dao.get(customer_id)
        if profile is not None:
            await self.profile_cache.set(customer_id, profile)
        return profile

    @staticmethod
    def _event(
        request: AdvisorChatRequest,
        *,
        event_type: AgentEventType,
        source: AgentType,
        targets: list[AgentType],
        trace_id: str,
        payload: dict[str, Any],
        causation_id: str | None = None,
    ) -> AgentEvent:
        return AgentEvent(
            event_type=event_type,
            source_agent=source,
            target_agents=targets,
            payload=payload,
            trace_id=trace_id,
            session_id=request.session_id,
            user_id=request.user_id,
            customer_id=request.customer_id,
            correlation_id=request.session_id,
            causation_id=causation_id,
            deduplication_key=(
                f"{event_type.value}:{request.session_id}:"
                f"{request.customer_id}"
            ),
        )
