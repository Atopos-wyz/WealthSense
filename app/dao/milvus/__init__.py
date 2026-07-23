"""Milvus 连接管理。"""

from app.dao.milvus.connection import MilvusConnectionManager
from app.dao.milvus.knowledge import (
    COLLECTION_BY_TYPE,
    FAQ_COLLECTION,
    POLICY_COLLECTION,
    PRODUCT_COLLECTION,
    KnowledgeVectorStore,
    VectorSearchHit,
)

__all__ = [
    "COLLECTION_BY_TYPE",
    "FAQ_COLLECTION",
    "KnowledgeVectorStore",
    "MilvusConnectionManager",
    "POLICY_COLLECTION",
    "PRODUCT_COLLECTION",
    "VectorSearchHit",
]
