"""知识库元数据、切片、向量入库与检索编排。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path

from app.dao.milvus import (
    COLLECTION_BY_TYPE,
    FAQ_COLLECTION,
    POLICY_COLLECTION,
    PRODUCT_COLLECTION,
    KnowledgeVectorStore,
)
from app.dao.mysql import KnowledgeRepository
from app.models.entities import KnowledgeMeta
from app.models.schemas.knowledge import (
    KnowledgeSearchResult,
    KnowledgeUpdateRequest,
)
from app.service.bootstrap import create_required_tables
from app.tool.document import DocumentParser
from app.tool.embedding import EmbeddingTool
from app.utils.exceptions import ConflictError, ResourceNotFoundError


class KnowledgeService:
    def __init__(
        self,
        *,
        repository: KnowledgeRepository,
        vector_store: KnowledgeVectorStore,
        parser: DocumentParser,
        embedding: EmbeddingTool,
        mysql,
        default_min_score: float,
    ) -> None:
        self._repository = repository
        self._vector_store = vector_store
        self._parser = parser
        self._embedding = embedding
        self._mysql = mysql
        self._default_min_score = default_min_score
        self._initialize_lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._initialize_lock:
            if self._initialized:
                return
            await create_required_tables(self._mysql)
            await self._vector_store.initialize()
            self._initialized = True

    async def ingest(
        self,
        *,
        filename: str,
        data: bytes,
        knowledge_type: str,
        title: str | None = None,
        source_path: str | None = None,
    ) -> tuple[KnowledgeMeta, int]:
        if knowledge_type not in COLLECTION_BY_TYPE:
            raise ValueError(f"不支持的知识类型：{knowledge_type}")
        await self.initialize()
        chunks = self._parser.parse_bytes(filename, data)
        collection = COLLECTION_BY_TYPE[knowledge_type]
        existing = await self._repository.find_active_by_source(filename)
        expire_at = self._default_expire_at(knowledge_type)
        resolved_title = title or Path(filename).stem

        if existing is None:
            item = await self._repository.create(
                KnowledgeMeta(
                    knowledge_type=knowledge_type,
                    title=resolved_title,
                    source_file=filename,
                    minio_path=source_path,
                    milvus_collection=collection,
                    version="v1",
                    status="草稿",
                    expire_at=expire_at,
                )
            )
        else:
            await self._vector_store.delete_by_source(
                existing.milvus_collection,
                existing.id,
            )
            item = await self._repository.update(
                existing,
                {
                    "knowledge_type": knowledge_type,
                    "title": resolved_title,
                    "minio_path": source_path,
                    "milvus_collection": collection,
                    "status": "草稿",
                    "expire_at": expire_at,
                },
            )

        try:
            vectors = await self._embedding.embed_documents(
                [chunk.content for chunk in chunks]
            )
            now = datetime.now().astimezone().isoformat()
            records = [
                {
                    "content": chunk.content,
                    "embedding": vector,
                    "metadata": {
                        "source": filename,
                        "source_id": item.id,
                        "type": knowledge_type,
                        "title": chunk.title,
                        "chunk_index": chunk.chunk_index,
                        "create_time": now,
                    },
                }
                for chunk, vector in zip(chunks, vectors, strict=True)
            ]
            inserted = await self._vector_store.insert(collection, records)
            if inserted != len(records):
                raise RuntimeError(
                    f"Milvus 写入数量不一致：expected={len(records)}, actual={inserted}"
                )
        except Exception:
            await self._repository.update(item, {"status": "草稿"})
            raise

        item = await self._repository.update(item, {"status": "有效"})
        return item, len(chunks)

    async def get(self, knowledge_id: int) -> KnowledgeMeta:
        await self.initialize()
        item = await self._repository.get(knowledge_id)
        if item is None:
            raise ResourceNotFoundError("知识文档")
        return item

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        knowledge_type: str | None,
        status: str | None,
    ):
        await self.initialize()
        return await self._repository.list(
            page=page,
            page_size=page_size,
            knowledge_type=knowledge_type,
            status=status,
        )

    async def update(
        self,
        knowledge_id: int,
        request: KnowledgeUpdateRequest,
    ) -> KnowledgeMeta:
        item = await self.get(knowledge_id)
        changes = request.model_dump(exclude_unset=True)
        requested_type = changes.get("knowledge_type")
        if requested_type and requested_type != item.knowledge_type:
            raise ConflictError("知识类型变更需要重新上传文档以同步向量集合")
        if not changes:
            return item
        return await self._repository.update(item, changes)

    async def delete(self, knowledge_id: int) -> KnowledgeMeta:
        item = await self.get(knowledge_id)
        if item.status != "过期":
            await self._vector_store.delete_by_source(
                item.milvus_collection,
                item.id,
            )
            item = await self._repository.mark_expired(item)
        return item

    async def search(
        self,
        *,
        query: str,
        top_k: int,
        min_score: float | None = None,
        knowledge_type: str | None = None,
    ) -> list[KnowledgeSearchResult]:
        await self.initialize()
        threshold = (
            self._default_min_score if min_score is None else float(min_score)
        )
        vector = await self._embedding.embed_query(query)
        if knowledge_type:
            collections = [COLLECTION_BY_TYPE[knowledge_type]]
        else:
            collections = [FAQ_COLLECTION, PRODUCT_COLLECTION, POLICY_COLLECTION]
        results = await asyncio.gather(
            *(
                self._vector_store.search(
                    collection,
                    vector,
                    top_k=top_k,
                    min_score=threshold,
                )
                for collection in collections
            )
        )
        hits = sorted(
            (hit for collection_hits in results for hit in collection_hits),
            key=lambda hit: hit.score,
            reverse=True,
        )[:top_k]
        source_ids = {
            int(hit.metadata["source_id"])
            for hit in hits
            if "source_id" in hit.metadata
        }
        metadata = await self._repository.get_many(source_ids)
        response: list[KnowledgeSearchResult] = []
        for hit in hits:
            source_id = int(hit.metadata.get("source_id", 0))
            item = metadata.get(source_id)
            if item is None or item.status != "有效":
                continue
            response.append(
                KnowledgeSearchResult(
                    content=hit.content,
                    score=hit.score,
                    source=item.source_file,
                    source_id=item.id,
                    knowledge_type=item.knowledge_type,
                    title=str(hit.metadata.get("title") or item.title),
                    chunk_index=int(hit.metadata.get("chunk_index", 0)),
                )
            )
        return response

    @staticmethod
    def _default_expire_at(knowledge_type: str) -> datetime | None:
        now = datetime.now()
        if knowledge_type == "政策法规":
            return now + timedelta(days=365)
        if knowledge_type in {"产品说明", "操作指南", "市场研报"}:
            return now + timedelta(days=180)
        return None
