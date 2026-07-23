"""知识库 API 数据模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.models.schemas.response import PublicSchema

KnowledgeType = Literal["FAQ", "产品说明", "政策法规", "操作指南", "市场研报"]
KnowledgeStatus = Literal["有效", "过期", "草稿"]


class KnowledgeMetaResponse(PublicSchema):
    id: int
    knowledge_type: str
    title: str
    source_file: str
    minio_path: str | None
    milvus_collection: str
    version: str
    status: str
    expire_at: datetime | None
    create_time: datetime
    update_time: datetime


class KnowledgeUpdateRequest(PublicSchema):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    knowledge_type: KnowledgeType | None = None
    status: KnowledgeStatus | None = None
    expire_at: datetime | None = None


class KnowledgeSearchRequest(PublicSchema):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=50)
    min_score: float | None = Field(default=None, ge=0, le=1)
    knowledge_type: KnowledgeType | None = None


class KnowledgeSearchResult(PublicSchema):
    content: str
    score: float
    source: str
    source_id: int
    knowledge_type: str
    title: str
    chunk_index: int


class KnowledgeUploadResponse(PublicSchema):
    document: KnowledgeMetaResponse
    chunk_count: int
