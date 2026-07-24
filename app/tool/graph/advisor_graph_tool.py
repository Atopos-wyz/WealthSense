"""投顾场景 Neo4j 图谱增强工具。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.dao import DatabaseManager, get_database_manager
from app.utils.logger import get_logger


logger = get_logger(__name__)


class AdvisorGraphTool:
    """Neo4j 不可用时返回空增强信息，由 MySQL 结果继续完成主流程。"""

    def __init__(self, manager: DatabaseManager | None = None) -> None:
        self.manager = manager or get_database_manager()

    async def enrich_products(
        self,
        product_ids: Sequence[int],
    ) -> dict[int, dict[str, Any]]:
        if not product_ids:
            return {}
        query = """
        MATCH (p:Product)
        WHERE p.id IN $product_ids
        OPTIONAL MATCH (p)-[:BELONGS_TO]->(i:Industry)
        OPTIONAL MATCH (p)-[:MANAGED_BY]->(m:Manager)
        OPTIONAL MATCH (p)-[:TRADED_IN]->(market:Market)
        RETURN p.id AS product_id,
               collect(DISTINCT i.name) AS industries,
               collect(DISTINCT m.name) AS managers,
               collect(DISTINCT market.name) AS markets
        """
        rows = await self._query(query, product_ids=list(product_ids))
        return {
            int(row["product_id"]): {
                "industries": row.get("industries", []),
                "managers": row.get("managers", []),
                "markets": row.get("markets", []),
            }
            for row in rows
            if row.get("product_id") is not None
        }

    async def holding_paths(self, customer_id: int) -> list[dict[str, Any]]:
        query = """
        MATCH (c:Customer {id: $customer_id})-[:HOLDS]->(p:Product)
        OPTIONAL MATCH (p)-[:BELONGS_TO]->(i:Industry)
        RETURN p.id AS product_id, p.name AS product_name,
               collect(DISTINCT i.name) AS industries
        """
        return await self._query(query, customer_id=customer_id)

    async def _query(self, query: str, **parameters: Any) -> list[dict[str, Any]]:
        try:
            if not self.manager.neo4j.connected:
                await self.manager.neo4j.connect()
            async with self.manager.neo4j.session() as session:
                result = await session.run(query, **parameters)
                return [dict(record) async for record in result]
        except Exception as exc:
            logger.warning(
                "Neo4j 图谱增强不可用，投顾流程使用 MySQL 降级",
                extra={"database": "neo4j", "event": type(exc).__name__},
            )
            return []
