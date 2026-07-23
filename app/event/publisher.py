"""Agent 事件发布封装；兼容评估模块对 RedisEventPublisher 的导入。"""

from app.dao.redis.event_publisher import (
    EventPublisher,
    InMemoryEventPublisher,
    RedisEventPublisher,
)
from app.event.channels import EventChannel
from app.models.schemas.common import AgentEvent

__all__ = [
    "AgentEventPublisher",
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
        event: AgentEvent,
    ) -> None:
        await self.publisher.publish(channel, event)
