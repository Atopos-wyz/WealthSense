"""投顾 Agent 意图、事件、路由与配置模型测试。"""

import json
import unittest
from typing import Any

from app.agent.advisor.agent import AdvisorAgent
from app.agent.advisor.intent_router import classify_intent
from app.event.publisher import RedisEventPublisher, event_channels
from app.models.schemas.advisor import (
    AdvisorChatRequest,
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


class FakeRedis:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str) -> int:
        self.messages.append((channel, message))
        return 1


class FakePublisher:
    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    async def publish(self, event: AgentEvent) -> EventPublishReceipt:
        self.events.append(event)
        return EventPublishReceipt(
            event_id=event.event_id,
            published=True,
            channels=event_channels(event),
            subscriber_count=1,
        )

    async def publish_many(
        self,
        events: list[AgentEvent],
    ) -> list[EventPublishReceipt]:
        return [await self.publish(event) for event in events]


class MissingProfileCache:
    async def get(self, customer_id: int) -> None:
        return None

    async def set(
        self,
        customer_id: int,
        profile: dict[str, Any],
    ) -> None:
        return None


class MissingProfileDAO:
    async def get(self, customer_id: int) -> None:
        return None


class UnusedAssessmentDAO:
    async def get_latest(
        self,
        customer_id: int,
        valid_only: bool = False,
    ) -> None:
        raise AssertionError("画像缺失时不应继续查询风险测评")


class AdvisorIntentTest(unittest.TestCase):
    def test_explicit_hint_has_priority(self) -> None:
        request = AdvisorChatRequest(
            session_id="s-1",
            message="帮我看看持仓",
            user_id="u-1",
            customer_id=1,
            intent_hint=AdvisorIntent.ASSET_ALLOCATION,
        )

        self.assertEqual(
            classify_intent(request),
            AdvisorIntent.ASSET_ALLOCATION,
        )

    def test_multiple_products_route_to_comparison(self) -> None:
        request = AdvisorChatRequest(
            session_id="s-2",
            message="分析一下",
            user_id="u-1",
            customer_id=1,
            product_ids=[11, 12],
        )

        self.assertEqual(
            classify_intent(request),
            AdvisorIntent.PRODUCT_COMPARISON,
        )

    def test_c3_allocation_model_sums_to_one_hundred(self) -> None:
        service = AdvisorService(object())  # type: ignore[arg-type]
        advice, reasoning = service.allocate_assets(
            {
                "risk_level": "C3",
                "asset_allocation": {
                    "cash": 20,
                    "fixed_income": 40,
                    "equity": 30,
                    "alternative": 10,
                },
            }
        )

        self.assertEqual(
            sum(item.target_ratio for item in advice.items),
            100,
        )
        self.assertEqual(advice.risk_level.value, "C3")
        self.assertEqual(len(reasoning), 3)


class AdvisorEventTest(unittest.IsolatedAsyncioTestCase):
    async def test_publisher_uses_global_type_and_target_channels(self) -> None:
        client = FakeRedis()
        publisher = RedisEventPublisher(client=client)  # type: ignore[arg-type]
        event = AgentEvent(
            event_type=AgentEventType.ASSESSMENT_REQUIRED,
            source_agent=AgentType.ADVISOR,
            target_agents=[AgentType.RISK],
            payload={"requested_action": "START_RISK_ASSESSMENT"},
            trace_id="trace-1",
            customer_id=1,
        )

        receipt = await publisher.publish(event)

        self.assertTrue(receipt.published)
        self.assertEqual(
            {channel for channel, _ in client.messages},
            {
                "event:all",
                "event:type:assessment.required",
                "event:agent:risk",
            },
        )
        published_event = json.loads(client.messages[0][1])
        self.assertEqual(published_event["event_id"], event.event_id)
        self.assertEqual(published_event["trace_id"], "trace-1")

    async def test_missing_profile_routes_to_risk_agent(self) -> None:
        publisher = FakePublisher()
        agent = AdvisorAgent(
            object(),  # type: ignore[arg-type]
            publisher=publisher,  # type: ignore[arg-type]
            service=object(),  # type: ignore[arg-type]
            profile_dao=MissingProfileDAO(),  # type: ignore[arg-type]
            assessment_dao=UnusedAssessmentDAO(),  # type: ignore[arg-type]
            profile_cache=MissingProfileCache(),  # type: ignore[arg-type]
        )
        request = AdvisorChatRequest(
            session_id="session-missing",
            message="推荐一款理财产品",
            user_id="user-1",
            customer_id=7,
        )

        response = await agent.chat(request)

        self.assertEqual(response.route, AdvisorRoute.RISK_AGENT)
        self.assertEqual(
            response.intent,
            AdvisorIntent.RISK_ASSESSMENT_REQUIRED,
        )
        self.assertFalse(response.profile_found)
        self.assertEqual(
            [event.event_type for event in publisher.events],
            [
                AgentEventType.ADVISOR_REQUESTED,
                AgentEventType.PROFILE_MISSING,
                AgentEventType.ASSESSMENT_REQUIRED,
            ],
        )
        risk_event = publisher.events[-1]
        self.assertIn(AgentType.RISK, risk_event.target_agents)
        self.assertEqual(
            risk_event.payload["requested_action"],
            "START_RISK_ASSESSMENT",
        )
