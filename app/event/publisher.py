from app.dao.redis.event_publisher import EventPublisher
from app.event.channels import EventChannel
from app.models.schemas.common import AgentEvent


class AgentEventPublisher:
    def __init__(self, publisher: EventPublisher) -> None:
        self.publisher = publisher

    async def publish(
        self,
        channel: EventChannel,
        event: AgentEvent,
    ) -> None:
        await self.publisher.publish(channel, event)

