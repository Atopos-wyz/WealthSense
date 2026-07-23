"""异步 Redis 连接生命周期管理。"""

from __future__ import annotations

import asyncio

from redis.asyncio import Redis

from app.config.settings import Settings
from app.utils.exceptions import DatabaseConnectionError


class RedisConnectionManager:
    """管理单个 redis-py 异步客户端及其连接池。"""

    name = "redis"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Redis | None = None
        self._connect_lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._client is not None

    @property
    def client(self) -> Redis:
        if self._client is None:
            raise RuntimeError("Redis 连接尚未初始化")
        return self._client

    async def connect(self) -> None:
        if self._client is not None:
            return

        async with self._connect_lock:
            if self._client is not None:
                return

            client = Redis(
                host=self._settings.redis_host,
                port=self._settings.redis_port,
                db=self._settings.redis_db,
                password=self._settings.redis_password.get_secret_value(),
                decode_responses=True,
                max_connections=self._settings.redis_max_connections,
                socket_connect_timeout=self._settings.database_connect_timeout_seconds,
                socket_timeout=self._settings.database_connect_timeout_seconds,
                health_check_interval=30,
            )
            try:
                await client.ping()
            except Exception as exc:
                await client.aclose()
                raise DatabaseConnectionError(self.name) from exc

            self._client = client

    async def health_check(self) -> bool:
        try:
            if self._client is None:
                await self.connect()
            return bool(await self.client.ping())
        except Exception:
            return False

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
        self._client = None
