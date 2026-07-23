"""本模块负责创建当前职责范围内的数据库表。"""

from __future__ import annotations

from app.dao.mysql import MySQLConnectionManager
from app.models.entities import Base


async def create_required_tables(mysql: MySQLConnectionManager) -> None:
    await mysql.connect()
    async with mysql.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
