"""需求文档定义的三个知识向量集合。"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pymilvus import DataType, MilvusClient

from app.dao.milvus.connection import MilvusConnectionManager

FAQ_COLLECTION = "fin_faq_collection"
PRODUCT_COLLECTION = "fin_product_collection"
POLICY_COLLECTION = "fin_policy_collection"

COLLECTION_BY_TYPE = {
    "FAQ": FAQ_COLLECTION,
    "产品说明": PRODUCT_COLLECTION,
    "操作指南": PRODUCT_COLLECTION,
    "市场研报": PRODUCT_COLLECTION,
    "政策法规": POLICY_COLLECTION,
}


@dataclass(frozen=True, slots=True)
class VectorSearchHit:
    content: str
    score: float
    metadata: dict[str, Any]


class KnowledgeVectorStore:
    def __init__(
        self,
        manager: MilvusConnectionManager,
        *,
        dimension: int,
    ) -> None:
        self._manager = manager
        self._dimension = dimension

    async def initialize(self) -> None:
        await self._manager.connect()
        existing = set(await asyncio.to_thread(self._manager.client.list_collections))
        for collection_name in (
            FAQ_COLLECTION,
            PRODUCT_COLLECTION,
            POLICY_COLLECTION,
        ):
            if collection_name not in existing:
                await asyncio.to_thread(self._create_collection, collection_name)

    def _create_collection(self, collection_name: str) -> None:
        schema = MilvusClient.create_schema(
            auto_id=True,
            enable_dynamic_field=False,
        )
        schema.add_field(
            field_name="id",
            datatype=DataType.INT64,
            is_primary=True,
            auto_id=True,
        )
        schema.add_field(
            field_name="content",
            datatype=DataType.VARCHAR,
            max_length=8192,
        )
        schema.add_field(
            field_name="embedding",
            datatype=DataType.FLOAT_VECTOR,
            dim=self._dimension,
        )
        schema.add_field(field_name="metadata", datatype=DataType.JSON)

        index_params = MilvusClient.prepare_index_params()
        if collection_name == FAQ_COLLECTION:
            index_params.add_index(
                field_name="embedding",
                index_name="embedding_hnsw",
                index_type="HNSW",
                metric_type="COSINE",
                params={"M": 16, "efConstruction": 200},
            )
        else:
            index_params.add_index(
                field_name="embedding",
                index_name="embedding_ivf_flat",
                index_type="IVF_FLAT",
                metric_type="COSINE",
                params={"nlist": 128},
            )
        self._manager.client.create_collection(
            collection_name=collection_name,
            schema=schema,
            index_params=index_params,
        )

    async def insert(
        self,
        collection_name: str,
        records: Sequence[dict[str, Any]],
    ) -> int:
        if not records:
            return 0
        await self.initialize()
        result = await asyncio.to_thread(
            self._manager.client.insert,
            collection_name=collection_name,
            data=list(records),
        )
        return int(result.get("insert_count", len(records)))

    async def search(
        self,
        collection_name: str,
        query_vector: list[float],
        *,
        top_k: int,
        min_score: float,
    ) -> list[VectorSearchHit]:
        await self.initialize()
        search_params = (
            {"metric_type": "COSINE", "params": {"ef": 64}}
            if collection_name == FAQ_COLLECTION
            else {"metric_type": "COSINE", "params": {"nprobe": 16}}
        )
        results = await asyncio.to_thread(
            self._manager.client.search,
            collection_name=collection_name,
            data=[query_vector],
            anns_field="embedding",
            limit=top_k,
            output_fields=["content", "metadata"],
            search_params=search_params,
            consistency_level="Strong",
        )
        hits: list[VectorSearchHit] = []
        for hit in results[0] if results else []:
            score = float(hit.get("distance", 0))
            if score < min_score:
                continue
            entity = hit.get("entity", {})
            hits.append(
                VectorSearchHit(
                    content=str(entity.get("content", "")),
                    score=score,
                    metadata=dict(entity.get("metadata") or {}),
                )
            )
        return hits

    async def delete_by_source(
        self,
        collection_name: str,
        source_id: int,
    ) -> int:
        await self.initialize()
        result = await asyncio.to_thread(
            self._manager.client.delete,
            collection_name=collection_name,
            filter=f'metadata["source_id"] == {int(source_id)}',
        )
        return int(result.get("delete_count", 0))
