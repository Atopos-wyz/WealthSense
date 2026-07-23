"""Agent 事件发布封装；兼容评估模块对 RedisEventPublisher 的导入。"""

from app.dao.redis.event_publisher import (
    DurableEventPublisher,
    EventPublisher,
    InMemoryEventPublisher,
    RedisEventPublisher as _RedisEventPublisher,
)
from app.event.channels import EventChannel
from app.models.schemas.common import AgentEvent as CommonAgentEvent

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
    """兼容投顾 / 画像模块的无参构造事件发布器（内存版）。

    投顾与画像模块直接通过 ``RedisEventPublisher()`` 实例化本类；
    事件写入内存列表，供测试验证。
    """

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    async def publish(self, event: object) -> None:
        """仅接收单个事件对象（投顾模块约定）。"""
        self.events.append(
            (getattr(event, "event_type", ""), event.model_dump(mode="json")),
        )
