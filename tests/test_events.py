import unittest
from datetime import timedelta

from app.dao.mysql.operation_repository import InMemoryOperationRepository
from app.dao.redis.event_publisher import (
    DurableEventPublisher,
    RedisEventPublisher,
)
from app.event.channels import EventChannel
from app.event.event_router import OperatorEventRouter
from app.models.schemas.common import AgentEvent, AgentId, utc_now
from app.utils.exceptions import (
    OperatorConflictError as ConflictError,
    OperatorError,
)
from tests.helpers import build_test_service


class FailOncePublisher:
    def __init__(self) -> None:
        self.failed = False
        self.events: list[tuple[EventChannel, AgentEvent]] = []

    async def publish(
        self,
        channel: EventChannel,
        event: AgentEvent,
    ) -> None:
        if not self.failed:
            self.failed = True
            raise ConnectionError("redis unavailable")
        self.events.append((channel, event))


class FakeRedis:
    def __init__(self) -> None:
        self.stream_entries: list[tuple] = []
        self.pubsub_entries: list[tuple] = []

    async def xadd(self, *args, **kwargs):
        self.stream_entries.append((args, kwargs))
        return "1-0"

    async def publish(self, *args):
        self.pubsub_entries.append(args)
        return 0


class EventTests(unittest.IsolatedAsyncioTestCase):
    async def test_outbox_retries_failed_publication(self) -> None:
        repository = InMemoryOperationRepository()
        transport = FailOncePublisher()
        publisher = DurableEventPublisher(repository, transport)
        event = AgentEvent(
            event_id="EVT_OUTBOX",
            event_type="operation.accepted",
            source_agent=AgentId.OPERATOR,
            target_agents=[AgentId.ADVISOR],
        )
        await publisher.publish(EventChannel.AGENT_RESULT, event)
        self.assertEqual(repository.outbox[event.event_id]["status"], "pending")
        self.assertEqual(await publisher.flush_pending(), 1)
        self.assertEqual(repository.outbox[event.event_id]["status"], "sent")

    async def test_event_type_must_use_expected_channel(self) -> None:
        service, _, transport = build_test_service()
        router = OperatorEventRouter(service)
        event = AgentEvent(
            event_id="EVT_WRONG_CHANNEL",
            event_type="risk.check.completed",
            source_agent=AgentId.RISK,
            target_agents=[AgentId.OPERATOR],
        )
        await router.handle(EventChannel.OPERATOR_COMMAND, event)
        self.assertTrue(
            any(
                channel == EventChannel.AGENT_RESULT
                and published.event_type == "operation.request.rejected"
                for channel, published in transport.events
            )
        )

    async def test_control_event_requires_expiry_and_is_deduplicated(self) -> None:
        service, _, _ = build_test_service()
        event = AgentEvent(
            event_id="EVT_CONTROL",
            event_type="operation.cancel.requested",
            source_agent=AgentId.ADVISOR,
            target_agents=[AgentId.OPERATOR],
            expires_at=utc_now() + timedelta(minutes=1),
        )
        await service.claim_control_event(event)
        with self.assertRaises(ConflictError):
            await service.claim_control_event(event)
        service.repository.processed_events[event.event_id][
            "lease_expires_at"
        ] = utc_now() - timedelta(seconds=1)
        await service.claim_control_event(event)
        expired = event.model_copy(
            update={
                "event_id": "EVT_CONTROL_EXPIRED",
                "expires_at": utc_now() - timedelta(seconds=1),
            }
        )
        with self.assertRaises(OperatorError):
            await service.claim_control_event(expired)

    async def test_redis_event_is_durable_without_live_subscriber(self) -> None:
        redis = FakeRedis()
        publisher = RedisEventPublisher(
            redis,
            {
                "operator": "operator-secret",
                "customer": "customer-secret",
                "advisor": "advisor-secret",
                "risk": "risk-secret",
                "analyst": "analyst-secret",
            },
        )
        event = AgentEvent(
            event_id="EVT_STREAM",
            event_type="operation.succeeded",
            source_agent=AgentId.OPERATOR,
            target_agents=[AgentId.ADVISOR],
        )
        await publisher.publish(EventChannel.AGENT_RESULT, event)
        self.assertEqual(len(redis.stream_entries), 1)
        self.assertEqual(len(redis.pubsub_entries), 1)
