"""支持异步安全阻塞调用的 Milvus 客户端生命周期管理。"""

from __future__ import annotations

import asyncio
from typing import Any

from app.config.settings import Settings
from app.utils.exceptions import DatabaseConnectionError


class MilvusConnectionManager:
    """管理单个 MilvusClient，并将其阻塞 API 与事件循环隔离。"""

    name = "milvus"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Any | None = None
        self._connect_lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._client is not None

    @property
    def client(self) -> Any:
        if self._client is None:
            raise RuntimeError("Milvus 连接尚未初始化")
        return self._client

    async def connect(self) -> None:
        if self._client is not None:
            return

        async with self._connect_lock:
            if self._client is not None:
                return

            client: Any | None = None
            try:
                from pymilvus import MilvusClient

                client = await asyncio.to_thread(
                    MilvusClient,
                    uri=self._settings.milvus_uri,
                    user=self._settings.milvus_user,
                    password=self._settings.milvus_root_password.get_secret_value(),
                    db_name=self._settings.milvus_database,
                    timeout=self._settings.database_connect_timeout_seconds,
                )
                await asyncio.to_thread(client.list_collections)
            except Exception as exc:
                if client is not None:
                    try:
                        await asyncio.to_thread(client.close)
                    except Exception:
                        pass
                raise DatabaseConnectionError(self.name) from exc

            self._client = client

    async def health_check(self) -> bool:
        try:
            if self._client is None:
                await self.connect()
            await asyncio.to_thread(self.client.list_collections)
            return True
        except Exception:
            return False

    async def close(self) -> None:
        if self._client is not None:
            await asyncio.to_thread(self._client.close)
        self._client = None
