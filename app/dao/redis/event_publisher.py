from typing import Protocol

from redis.asyncio import Redis

from app.event.channels import EventChannel
from app.models.schemas.common import AgentEvent


class EventPublisher(Protocol):
    async def publish(
        self,
        channel: EventChannel,
        event: AgentEvent,
    ) -> None: ...


class InMemoryEventPublisher:
    def __init__(self) -> None:
        self.events: list[tuple[EventChannel, AgentEvent]] = []

    async def publish(
        self,
        channel: EventChannel,
        event: AgentEvent,
    ) -> None:
        self.events.append((channel, event.model_copy(deep=True)))


class RedisEventPublisher:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def publish(
        self,
        channel: EventChannel,
        event: AgentEvent,
    ) -> None:
        await self.redis.publish(channel.value, event.model_dump_json())

