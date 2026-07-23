import logging
from typing import Any, Protocol

from redis.asyncio import Redis

from app.event.channels import EventChannel
from app.models.schemas.common import AgentEvent
from app.utils.security import sign_agent_event

logger = logging.getLogger(__name__)


class EventPublisher(Protocol):
    async def publish(
        self,
        channel: EventChannel,
        event: AgentEvent,
    ) -> None: ...


class OutboxRepository(Protocol):
    async def enqueue_outbox(
        self,
        event_id: str,
        channel: str,
        payload: dict[str, Any],
    ) -> None: ...
    async def mark_outbox_sent(self, event_id: str) -> None: ...
    async def list_pending_outbox(
        self,
        limit: int = 100,
    ) -> list[dict[str, Any]]: ...


class InMemoryEventPublisher:
    def __init__(
        self,
        hmac_secrets: dict[str, str] | None = None,
    ) -> None:
        self.events: list[tuple[EventChannel, AgentEvent]] = []
        self.hmac_secrets = hmac_secrets or {
            agent: f"test-{agent}-event-secret"
            for agent in ("customer", "advisor", "risk", "analyst", "operator")
        }

    async def publish(
        self,
        channel: EventChannel,
        event: AgentEvent,
    ) -> None:
        signed = sign_agent_event(
            event,
            self.hmac_secrets[event.source_agent.value],
        )
        self.events.append((channel, signed.model_copy(deep=True)))


class RedisEventPublisher:
    def __init__(
        self,
        redis: Redis,
        hmac_secrets: dict[str, str],
        stream_key: str = "agent:events:durable",
    ) -> None:
        self.redis = redis
        self.hmac_secrets = hmac_secrets
        self.stream_key = stream_key

    async def publish(
        self,
        channel: EventChannel,
        event: AgentEvent,
    ) -> None:
        signed = sign_agent_event(
            event,
            self.hmac_secrets[event.source_agent.value],
        )
        serialized = signed.model_dump_json()
        await self.redis.xadd(
            self.stream_key,
            {
                "event_id": signed.event_id,
                "channel": channel.value,
                "event": serialized,
            },
            maxlen=100000,
            approximate=True,
        )
        await self.redis.publish(
            channel.value,
            serialized,
        )


class DurableEventPublisher:
    """Persists events before Redis publication and retries unsent rows."""

    def __init__(
        self,
        repository: OutboxRepository,
        transport: EventPublisher,
    ) -> None:
        self.repository = repository
        self.transport = transport

    async def publish(
        self,
        channel: EventChannel,
        event: AgentEvent,
    ) -> None:
        await self.repository.enqueue_outbox(
            event.event_id,
            channel.value,
            event.model_dump(mode="json"),
        )
        try:
            await self.transport.publish(channel, event)
        except Exception:
            logger.error(
                "event publication deferred to outbox retry: %s",
                event.event_id,
            )
            return
        await self.repository.mark_outbox_sent(event.event_id)

    async def flush_pending(self, limit: int = 100) -> int:
        pending = await self.repository.list_pending_outbox(limit)
        sent = 0
        for item in pending:
            event = AgentEvent.model_validate(item["payload"])
            await self.transport.publish(
                EventChannel(item["channel"]),
                event,
            )
            await self.repository.mark_outbox_sent(event.event_id)
            sent += 1
        return sent
