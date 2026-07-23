import json
from copy import deepcopy
from typing import Any, Protocol

from redis.asyncio import Redis


class StateStore(Protocol):
    async def put(
        self,
        key: str,
        value: dict[str, Any],
        ttl_seconds: int,
    ) -> None: ...
    async def get(self, key: str) -> dict[str, Any] | None: ...
    async def delete(self, key: str) -> None: ...
    async def acquire_lock(self, key: str, ttl_seconds: int) -> bool: ...


class InMemoryStateStore:
    def __init__(self) -> None:
        self.values: dict[str, dict[str, Any]] = {}
        self.locks: set[str] = set()

    async def put(
        self,
        key: str,
        value: dict[str, Any],
        ttl_seconds: int,
    ) -> None:
        del ttl_seconds
        self.values[key] = deepcopy(value)

    async def get(self, key: str) -> dict[str, Any] | None:
        value = self.values.get(key)
        return deepcopy(value) if value else None

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)
        self.locks.discard(key)

    async def acquire_lock(self, key: str, ttl_seconds: int) -> bool:
        del ttl_seconds
        if key in self.locks:
            return False
        self.locks.add(key)
        return True


class RedisStateStore:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def put(
        self,
        key: str,
        value: dict[str, Any],
        ttl_seconds: int,
    ) -> None:
        await self.redis.set(key, json.dumps(value), ex=ttl_seconds)

    async def get(self, key: str) -> dict[str, Any] | None:
        value = await self.redis.get(key)
        return json.loads(value) if value else None

    async def delete(self, key: str) -> None:
        await self.redis.delete(key)

    async def acquire_lock(self, key: str, ttl_seconds: int) -> bool:
        return bool(await self.redis.set(key, "1", ex=ttl_seconds, nx=True))

