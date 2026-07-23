"""项目四类数据库的统一生命周期管理器。"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from typing import Protocol

from app.config.settings import Settings, get_settings
from app.dao.milvus import MilvusConnectionManager
from app.dao.mysql import MySQLConnectionManager
from app.dao.neo4j import Neo4jConnectionManager
from app.dao.redis import RedisConnectionManager


class ConnectionManager(Protocol):
    name: str

    @property
    def connected(self) -> bool: ...

    async def connect(self) -> None: ...

    async def health_check(self) -> bool: ...

    async def close(self) -> None: ...


class DatabaseManager:
    """协调所有数据库的启动、健康检查与关闭。"""

    def __init__(self, settings: Settings) -> None:
        self.mysql = MySQLConnectionManager(settings)
        self.redis = RedisConnectionManager(settings)
        self.neo4j = Neo4jConnectionManager(settings)
        self.milvus = MilvusConnectionManager(settings)
        self._connections: tuple[ConnectionManager, ...] = (
            self.mysql,
            self.redis,
            self.neo4j,
            self.milvus,
        )

    async def connect_all(self) -> None:
        connected: list[ConnectionManager] = []
        try:
            for connection in self._connections:
                await connection.connect()
                connected.append(connection)
        except Exception:
            for connection in reversed(connected):
                await connection.close()
            raise

    async def health_check(self) -> Mapping[str, bool]:
        return {
            connection.name: await connection.health_check()
            for connection in self._connections
        }

    async def close_all(self) -> None:
        first_error: Exception | None = None
        for connection in reversed(self._connections):
            try:
                await connection.close()
            except Exception as exc:
                first_error = first_error or exc
        if first_error is not None:
            raise first_error

    async def __aenter__(self) -> DatabaseManager:
        await self.connect_all()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close_all()


@lru_cache(maxsize=1)
def get_database_manager() -> DatabaseManager:
    """返回进程级数据库生命周期管理器。"""

    return DatabaseManager(get_settings())
