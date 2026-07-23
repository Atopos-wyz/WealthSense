"""兼容 FastAPI Depends 的 MySQL 会话入口。"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.dao import get_database_manager


async def get_session() -> AsyncIterator[AsyncSession]:
    """为一次 HTTP 请求提供数据库会话。"""

    manager = get_database_manager()
    async with manager.mysql.session() as session:
        yield session
