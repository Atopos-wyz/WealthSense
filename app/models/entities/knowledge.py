"""知识库元数据实体。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.entities.base import Base, TimestampMixin


class KnowledgeMeta(TimestampMixin, Base):
    """需求文档定义的 fin_knowledge_meta 表。"""

    __tablename__ = "fin_knowledge_meta"
    __table_args__ = (
        Index("ix_knowledge_type_status", "knowledge_type", "status"),
        Index("ix_knowledge_expire_at", "expire_at"),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_0900_ai_ci"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    knowledge_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source_file: Mapped[str] = mapped_column(String(255), nullable=False)
    minio_path: Mapped[str | None] = mapped_column(String(512))
    milvus_collection: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="有效")
    expire_at: Mapped[datetime | None] = mapped_column(DateTime)
