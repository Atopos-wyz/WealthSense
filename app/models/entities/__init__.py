"""WealthSense 持久化实体。"""

from app.models.entities.base import Base
from app.models.entities.conversation import ConversationArchive
from app.models.entities.knowledge import KnowledgeMeta

__all__ = ["Base", "ConversationArchive", "KnowledgeMeta"]
