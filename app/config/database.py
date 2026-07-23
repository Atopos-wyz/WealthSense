from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.dao import get_database_manager
from app.models.entities import Base


def create_engine(mysql_url: str) -> AsyncEngine:
    return create_async_engine(mysql_url, pool_pre_ping=True)


def create_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_tables(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    """为一次 HTTP 请求提供数据库会话（通过 DatabaseManager 管理）。"""
    manager = get_database_manager()
    async with manager.mysql.session() as session:
        yield session

