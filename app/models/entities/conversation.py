"""Agent 会话归档实体。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, Index, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.entities.base import Base, TimestampMixin


class ConversationArchive(TimestampMixin, Base):
    __tablename__ = "conversation_archive"
    __table_args__ = (
        Index("ix_conversation_session_time", "session_id", "create_time"),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_0900_ai_ci"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_type: Mapped[str] = mapped_column(String(32), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    extra_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
