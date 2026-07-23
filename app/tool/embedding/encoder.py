"""BGE 中文向量化及受控降级实现。"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
from typing import Any


class EmbeddingTool:
    def __init__(
        self,
        *,
        provider: str,
        model_name: str,
        dimension: int,
        batch_size: int,
    ) -> None:
        self.provider = provider
        self.model_name = model_name
        self.dimension = dimension
        self.batch_size = batch_size
        self._model: Any | None = None
        self._load_lock = asyncio.Lock()

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self.provider == "hashing":
            return [self._hashing_vector(text) for text in texts]
        model = await self._get_bge_model()
        vectors = await asyncio.to_thread(
            model.encode,
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        result = [vector.tolist() for vector in vectors]
        self._validate_dimension(result)
        return result

    async def embed_query(self, text: str) -> list[float]:
        if self.provider == "hashing":
            return self._hashing_vector(text)
        model = await self._get_bge_model()
        query = f"为这个句子生成表示以用于检索相关文章：{text}"
        vector = await asyncio.to_thread(
            model.encode,
            query,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        result = vector.tolist()
        self._validate_dimension([result])
        return result

    async def _get_bge_model(self):
        if self._model is not None:
            return self._model
        async with self._load_lock:
            if self._model is None:
                from sentence_transformers import SentenceTransformer

                self._model = await asyncio.to_thread(
                    SentenceTransformer,
                    self.model_name,
                )
        return self._model

    def _validate_dimension(self, vectors: list[list[float]]) -> None:
        if any(len(vector) != self.dimension for vector in vectors):
            actual = len(vectors[0]) if vectors else 0
            raise ValueError(
                f"Embedding 维度不一致：配置={self.dimension}，实际={actual}"
            )

    def _hashing_vector(self, text: str) -> list[float]:
        """无模型环境的确定性测试降级，不作为生产 Embedding。"""

        normalized = re.sub(r"\s+", "", text.lower())
        tokens = list(normalized)
        tokens.extend(
            normalized[index : index + 2]
            for index in range(max(0, len(normalized) - 1))
        )
        vector = [0.0] * self.dimension
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector
