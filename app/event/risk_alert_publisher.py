"""事件发布（默认内存总线；可选 Redis Pub/Sub + 演示用快照缓存）。"""

from __future__ import annotations

import json
from typing import Any, Protocol

from app.dao.redis.connection import RedisConnectionManager
from app.event.channels import RISK_ALERT_CHANNEL
from app.event.payloads import RiskAlertEvent
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 演示用旁路缓存（MySQL 仍为真相；Pub/Sub 仍不持久）
RISK_ALERT_CACHE_KEY = "risk:alert:{alert_id}"
RISK_ALERT_RECENT_KEY = "risk:alert:recent"
RISK_ALERT_CACHE_TTL_SECONDS = 86400  # 24h
RISK_ALERT_RECENT_MAX = 50


class RiskAlertPublisher(Protocol):
    async def publish_risk_alert(self, event: RiskAlertEvent) -> bool:
        """返回是否成功写入 Redis（仅内存时为 False）。"""


class InMemoryEventPublisher:
    """单测与无 Redis 时使用；消息留在 published 列表。"""

    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, Any]]] = []

    async def publish_risk_alert(self, event: RiskAlertEvent) -> bool:
        self.published.append((RISK_ALERT_CHANNEL, event.to_publish_dict()))
        return False


class RedisEventPublisher:
    def __init__(self, redis: RedisConnectionManager) -> None:
        self._redis = redis
        self.last_error: str | None = None

    async def publish_risk_alert(self, event: RiskAlertEvent) -> bool:
        if not self._redis.connected:
            await self._redis.connect()
        payload_dict = event.to_publish_dict()
        payload = json.dumps(payload_dict, ensure_ascii=False)
        client = self._redis.client
        receivers = await client.publish(RISK_ALERT_CHANNEL, payload)
        # 旁路快照：便于在 Redis 客户端看到 key（非可靠主存）
        cache_key = RISK_ALERT_CACHE_KEY.format(alert_id=event.alert_id)
        await client.set(cache_key, payload, ex=RISK_ALERT_CACHE_TTL_SECONDS)
        await client.lpush(RISK_ALERT_RECENT_KEY, payload)
        await client.ltrim(RISK_ALERT_RECENT_KEY, 0, RISK_ALERT_RECENT_MAX - 1)
        await client.expire(RISK_ALERT_RECENT_KEY, RISK_ALERT_CACHE_TTL_SECONDS)
        self.last_error = None
        logger.info(
            "已广播并缓存风控预警 channel=%s receivers=%s alert_id=%s cache=%s",
            RISK_ALERT_CHANNEL,
            receivers,
            event.alert_id,
            cache_key,
        )
        return True


class CompositeEventPublisher:
    """先写内存便于自证，再尝试 Redis（失败不阻断主链路）。"""

    def __init__(
        self,
        memory: InMemoryEventPublisher,
        redis_publisher: RedisEventPublisher | None = None,
    ) -> None:
        self.memory = memory
        self._redis = redis_publisher
        self.last_redis_error: str | None = None
        self.last_redis_ok: bool = False

    @property
    def redis_enabled(self) -> bool:
        return self._redis is not None

    async def publish_risk_alert(self, event: RiskAlertEvent) -> bool:
        await self.memory.publish_risk_alert(event)
        if self._redis is None:
            self.last_redis_ok = False
            self.last_redis_error = "未挂载 Redis 发布器"
            return False
        try:
            await self._redis.publish_risk_alert(event)
            self.last_redis_ok = True
            self.last_redis_error = None
            return True
        except Exception as exc:
            self.last_redis_ok = False
            self.last_redis_error = str(exc)
            logger.warning(
                "Redis 广播/缓存失败，已保留内存事件副本: %s",
                exc,
                exc_info=True,
            )
            return False
