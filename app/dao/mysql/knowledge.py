"""知识元数据与会话归档的数据访问。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select

from app.dao.mysql.connection import MySQLConnectionManager
from app.models.entities import ConversationArchive, KnowledgeMeta


class KnowledgeRepository:
    def __init__(self, mysql: MySQLConnectionManager) -> None:
        self._mysql = mysql

    async def create(self, item: KnowledgeMeta) -> KnowledgeMeta:
        async with self._mysql.session() as session:
            session.add(item)
            await session.commit()
            await session.refresh(item)
            return item

    async def get(self, knowledge_id: int) -> KnowledgeMeta | None:
        async with self._mysql.session() as session:
            return await session.get(KnowledgeMeta, knowledge_id)

    async def get_many(self, knowledge_ids: set[int]) -> dict[int, KnowledgeMeta]:
        if not knowledge_ids:
            return {}
        statement = select(KnowledgeMeta).where(KnowledgeMeta.id.in_(knowledge_ids))
        async with self._mysql.session() as session:
            items = (await session.execute(statement)).scalars().all()
            return {item.id: item for item in items}

    async def find_active_by_source(self, source_file: str) -> KnowledgeMeta | None:
        statement = (
            select(KnowledgeMeta)
            .where(
                KnowledgeMeta.source_file == source_file,
                KnowledgeMeta.status == "有效",
            )
            .order_by(KnowledgeMeta.id.desc())
            .limit(1)
        )
        async with self._mysql.session() as session:
            return (await session.execute(statement)).scalar_one_or_none()

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        knowledge_type: str | None = None,
        status: str | None = None,
    ) -> tuple[Sequence[KnowledgeMeta], int]:
        conditions = []
        if knowledge_type:
            conditions.append(KnowledgeMeta.knowledge_type == knowledge_type)
        if status:
            conditions.append(KnowledgeMeta.status == status)
        statement = (
            select(KnowledgeMeta)
            .where(*conditions)
            .order_by(KnowledgeMeta.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        count_statement = select(func.count(KnowledgeMeta.id)).where(*conditions)
        async with self._mysql.session() as session:
            items = (await session.execute(statement)).scalars().all()
            total = int((await session.execute(count_statement)).scalar_one())
            return items, total

    async def update(
        self,
        item: KnowledgeMeta,
        changes: dict[str, Any],
    ) -> KnowledgeMeta:
        async with self._mysql.session() as session:
            managed = await session.merge(item)
            for field, value in changes.items():
                setattr(managed, field, value)
            await session.commit()
            await session.refresh(managed)
            return managed

    async def mark_expired(self, item: KnowledgeMeta) -> KnowledgeMeta:
        return await self.update(item, {"status": "过期"})


class ConversationRepository:
    def __init__(self, mysql: MySQLConnectionManager) -> None:
        self._mysql = mysql

    async def archive(
        self,
        *,
        session_id: str,
        user_id: str,
        agent_type: str,
        role: str,
        content: str,
        extra_data: dict[str, Any] | None = None,
    ) -> None:
        item = ConversationArchive(
            session_id=session_id,
            user_id=user_id,
            agent_type=agent_type,
            role=role,
            content=content,
            extra_data=extra_data,
        )
        async with self._mysql.session() as session:
            session.add(item)
            await session.commit()

    async def history(
        self,
        session_id: str,
        *,
        limit: int,
    ) -> Sequence[ConversationArchive]:
        statement = (
            select(ConversationArchive)
            .where(ConversationArchive.session_id == session_id)
            .order_by(ConversationArchive.create_time.desc(), ConversationArchive.id.desc())
            .limit(limit)
        )
        async with self._mysql.session() as session:
            items = (await session.execute(statement)).scalars().all()
            return list(reversed(items))
