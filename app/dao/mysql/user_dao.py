"""系统用户 DAO。"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class UserDAO:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def exists(self, customer_id: int) -> bool:
        result = await self.session.execute(
            text("SELECT 1 FROM sys_user WHERE id = :customer_id LIMIT 1"),
            {"customer_id": customer_id},
        )
        return result.scalar_one_or_none() is not None
