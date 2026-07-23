"""客户画像 Redis Cache-Aside 访问。"""

import json
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError


PROFILE_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60


class ProfileCacheDAO:
    def __init__(self, client: Redis | None) -> None:
        self.client = client

    @staticmethod
    def key(customer_id: int) -> str:
        return f"profile:{customer_id}"

    async def get(self, customer_id: int) -> dict[str, Any] | None:
        if self.client is None:
            return None
        try:
            payload = await self.client.get(self.key(customer_id))
            if payload is None:
                return None
            await self.client.expire(
                self.key(customer_id),
                PROFILE_CACHE_TTL_SECONDS,
            )
            return json.loads(payload)
        except (RedisError, json.JSONDecodeError):
            return None

    async def set(self, customer_id: int, profile: dict[str, Any]) -> None:
        if self.client is None:
            return
        try:
            await self.client.set(
                self.key(customer_id),
                json.dumps(profile, ensure_ascii=False),
                ex=PROFILE_CACHE_TTL_SECONDS,
            )
        except RedisError:
            return

    async def delete(self, customer_id: int) -> None:
        if self.client is None:
            return
        try:
            await self.client.delete(self.key(customer_id))
        except RedisError:
            return
