import asyncio
import logging
from collections.abc import Awaitable, Callable

from redis.asyncio import Redis

from app.event.channels import EventChannel
from app.models.schemas.common import AgentEvent
from app.utils.security import verify_agent_event

logger = logging.getLogger(__name__)

EventHandler = Callable[[EventChannel, AgentEvent], Awaitable[None]]


class RedisEventSubscriber:
    def __init__(
        self,
        redis: Redis,
        hmac_secrets: dict[str, str],
    ) -> None:
        self.redis = redis
        self.hmac_secrets = hmac_secrets
        self._is_stopping = False

    async def listen(
        self,
        channels: list[EventChannel],
        handler: EventHandler,
    ) -> None:
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(*(channel.value for channel in channels))
        try:
            while not self._is_stopping:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if not message:
                    await asyncio.sleep(0.05)
                    continue
                try:
                    event = AgentEvent.model_validate_json(message["data"])
                    verify_agent_event(
                        event,
                        self.hmac_secrets[event.source_agent.value],
                    )
                    channel = EventChannel(str(message["channel"]))
                    await handler(channel, event)
                except Exception:
                    logger.exception("failed to process agent event")
        finally:
            await pubsub.unsubscribe()
            await pubsub.close()

    def stop(self) -> None:
        self._is_stopping = True
