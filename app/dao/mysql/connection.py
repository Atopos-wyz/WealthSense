"""基于异步 SQLAlchemy 的 MySQL 连接生命周期管理。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import URL, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config.settings import Settings
from app.utils.exceptions import DatabaseConnectionError


class MySQLConnectionManager:
    """管理应用共用的异步引擎与会话工厂。"""

    name = "mysql"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None
        self._connect_lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._engine is not None

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            raise RuntimeError("MySQL 连接尚未初始化")
        return self._engine

    async def connect(self) -> None:
        if self._engine is not None:
            return

        async with self._connect_lock:
            if self._engine is not None:
                return

            raw_password = self._settings.mysql_password.get_secret_value()
            url = URL.create(
                drivername="mysql+aiomysql",
                username=self._settings.mysql_user,
                password=raw_password if raw_password != "" else None,
                host=self._settings.mysql_host,
                port=self._settings.mysql_port,
                database=self._settings.mysql_database,
                query={"charset": "utf8mb4"},
            )
            engine = create_async_engine(
                url,
                # health_check() 已显式执行 SELECT 1；关闭驱动层预检，
                # 避免 aiomysql 的 ping(reconnect) 签名兼容问题。
                pool_pre_ping=False,
                pool_size=self._settings.mysql_pool_size,
                max_overflow=self._settings.mysql_max_overflow,
                pool_recycle=self._settings.mysql_pool_recycle_seconds,
                connect_args={
                    "connect_timeout": self._settings.database_connect_timeout_seconds
                },
            )
            try:
                async with engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
            except Exception as exc:
                await engine.dispose()
                raise DatabaseConnectionError(self.name) from exc

            self._engine = engine
            self._session_factory = async_sessionmaker(
                bind=engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=False,
            )

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        if self._session_factory is None:
            await self.connect()
        if self._session_factory is None:
            raise RuntimeError("MySQL 会话工厂不可用")

        async with self._session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    async def health_check(self) -> bool:
        try:
            if self._engine is None:
                await self.connect()
            async with self.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
        self._engine = None
        self._session_factory = None
