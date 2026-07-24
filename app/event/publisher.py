"""Agent 事件发布封装；兼容业务操作与投顾两套事件接口。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.dao.redis.event_publisher import (
    DurableEventPublisher,
    EventPublisher,
    InMemoryEventPublisher,
)
from app.event.channels import EventChannel
from app.models.schemas.common import AgentEvent as CommonAgentEvent
from app.models.schemas.event import (
    AgentEvent,
    EventPublishReceipt,
)

__all__ = [
    "AgentEventPublisher",
    "DurableEventPublisher",
    "EventPublisher",
    "InMemoryEventPublisher",
    "RedisEventPublisher",
]


class AgentEventPublisher:
    def __init__(self, publisher: EventPublisher) -> None:
        self.publisher = publisher

    async def publish(
        self,
        channel: EventChannel,
        event: CommonAgentEvent,
    ) -> None:
        await self.publisher.publish(channel, event)


class RedisEventPublisher:
    """投顾事件发布适配器。

    传入 Redis client 时发布真实 Pub/Sub；无参构造保留内存回执，
    让未配置 Redis 的开发环境仍可运行。
    """

    def __init__(self, client: Any | None = None) -> None:
        self.client = client
        self.events: list[tuple[str, dict[str, object]]] = []

    async def publish(self, event: AgentEvent) -> EventPublishReceipt:
        channels = event_channels(event)
        self.events.append(
            (str(event.event_type), event.model_dump(mode="json")),
        )
        if self.client is None:
            return EventPublishReceipt(
                event_id=event.event_id,
                published=False,
                channels=channels,
                error="redis_not_configured",
            )
        try:
            subscribers = 0
            payload = event.model_dump_json()
            for channel in channels:
                subscribers += int(await self.client.publish(channel, payload))
            return EventPublishReceipt(
                event_id=event.event_id,
                published=True,
                channels=channels,
                subscriber_count=subscribers,
            )
        except Exception as exc:
            return EventPublishReceipt(
                event_id=event.event_id,
                published=False,
                channels=channels,
                error=type(exc).__name__,
            )

    async def publish_many(
        self,
        events: Iterable[AgentEvent],
    ) -> list[EventPublishReceipt]:
        return [await self.publish(event) for event in events]


def event_channels(event: AgentEvent) -> list[str]:
    channels = {
        "event:all",
        f"event:type:{event.event_type}",
    }
    channels.update(
        f"event:agent:{target.value}"
        for target in event.target_agents
    )
    return sorted(channels)
