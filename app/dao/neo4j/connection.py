"""异步 Neo4j 驱动生命周期管理。"""

from __future__ import annotations

import asyncio

from neo4j import AsyncDriver, AsyncGraphDatabase

from app.config.settings import Settings
from app.utils.exceptions import DatabaseConnectionError


class Neo4jConnectionManager:
    """管理单个可复用的 Neo4j 异步驱动。"""

    name = "neo4j"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._driver: AsyncDriver | None = None
        self._connect_lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._driver is not None

    @property
    def driver(self) -> AsyncDriver:
        if self._driver is None:
            raise RuntimeError("Neo4j 连接尚未初始化")
        return self._driver

    async def connect(self) -> None:
        if self._driver is not None:
            return

        async with self._connect_lock:
            if self._driver is not None:
                return

            driver = AsyncGraphDatabase.driver(
                self._settings.neo4j_uri,
                auth=(
                    self._settings.neo4j_user,
                    self._settings.neo4j_password.get_secret_value(),
                ),
                max_connection_pool_size=self._settings.neo4j_max_connection_pool_size,
                connection_timeout=self._settings.database_connect_timeout_seconds,
            )
            try:
                await driver.verify_connectivity()
            except Exception as exc:
                await driver.close()
                raise DatabaseConnectionError(self.name) from exc

            self._driver = driver

    def session(self):
        return self.driver.session(database=self._settings.neo4j_database)

    async def health_check(self) -> bool:
        try:
            if self._driver is None:
                await self.connect()
            await self.driver.verify_connectivity()
            return True
        except Exception:
            return False

    async def close(self) -> None:
        if self._driver is not None:
            await self._driver.close()
        self._driver = None
