"""投顾推荐、持仓分析与对比查询 DAO。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession


class AdvisorDAO:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_suitable_products(
        self,
        risk_level: str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        result = await self.session.execute(
            text(
                """
                SELECT id, product_code, product_name, product_type,
                       risk_level, expected_return, min_amount, term_days,
                       fund_manager, industry, market, status
                FROM fin_product
                WHERE status = 'ACTIVE'
                  AND CASE risk_level
                        WHEN 'R1' THEN 1
                        WHEN 'R2' THEN 2
                        WHEN 'R3' THEN 3
                        WHEN 'R4' THEN 4
                        WHEN 'R5' THEN 5
                        WHEN 'C1' THEN 1
                        WHEN 'C2' THEN 2
                        WHEN 'C3' THEN 3
                        WHEN 'C4' THEN 4
                        WHEN 'C5' THEN 5
                        ELSE 99
                      END
                      <= CASE :customer_risk_level
                           WHEN 'C1' THEN 1
                           WHEN 'C2' THEN 2
                           WHEN 'C3' THEN 3
                           WHEN 'C4' THEN 4
                           WHEN 'C5' THEN 5
                           ELSE 0
                         END
                ORDER BY expected_return DESC, term_days ASC, id ASC
                LIMIT :limit
                """
            ),
            {
                "customer_risk_level": risk_level,
                "limit": limit,
            },
        )
        return [dict(row) for row in result.mappings().all()]

    async def list_holdings(
        self,
        customer_id: int,
    ) -> list[dict[str, Any]]:
        result = await self.session.execute(
            text(
                """
                SELECT h.id, h.customer_id, h.product_id, h.shares,
                       h.cost_amount, h.current_value, h.profit_loss,
                       h.profit_ratio, h.status, p.product_code,
                       p.product_name, p.product_type, p.risk_level,
                       p.expected_return, p.term_days, p.industry, p.market
                FROM fin_holdings h
                JOIN fin_product p ON p.id = h.product_id
                WHERE h.customer_id = :customer_id
                  AND h.status IN ('HOLDING', 'ACTIVE', '持有中')
                  AND h.current_value > 0
                ORDER BY h.current_value DESC, h.id ASC
                """
            ),
            {"customer_id": customer_id},
        )
        return [dict(row) for row in result.mappings().all()]

    async def get_products(
        self,
        product_ids: Sequence[int],
    ) -> list[dict[str, Any]]:
        if not product_ids:
            return []
        statement = text(
            """
            SELECT id, product_code, product_name, product_type,
                   risk_level, expected_return, min_amount, term_days,
                   fund_manager, industry, market, status
            FROM fin_product
            WHERE id IN :product_ids
            ORDER BY id ASC
            """
        ).bindparams(bindparam("product_ids", expanding=True))
        result = await self.session.execute(
            statement,
            {"product_ids": list(product_ids)},
        )
        return [dict(row) for row in result.mappings().all()]

    async def list_customer_holdings(
        self,
        customer_ids: Sequence[int],
    ) -> list[dict[str, Any]]:
        if not customer_ids:
            return []
        statement = text(
            """
            SELECT h.customer_id, h.product_id, h.current_value,
                   h.profit_loss, p.product_name, p.product_type,
                   p.risk_level, p.industry
            FROM fin_holdings h
            JOIN fin_product p ON p.id = h.product_id
            WHERE h.customer_id IN :customer_ids
              AND h.status IN ('HOLDING', 'ACTIVE', '持有中')
              AND h.current_value > 0
            ORDER BY h.customer_id, h.current_value DESC
            """
        ).bindparams(bindparam("customer_ids", expanding=True))
        result = await self.session.execute(
            statement,
            {"customer_ids": list(customer_ids)},
        )
        return [dict(row) for row in result.mappings().all()]

    async def record_suitability_checks(
        self,
        *,
        customer_id: int,
        customer_risk_level: str,
        products: Sequence[dict[str, Any]],
        trace_id: str,
    ) -> None:
        for product in products:
            await self.session.execute(
                text(
                    """
                    INSERT INTO fin_suitability_check (
                        customer_id, product_id, customer_risk_level,
                        product_risk_level, allowed, reason, trace_id
                    ) VALUES (
                        :customer_id, :product_id, :customer_risk_level,
                        :product_risk_level, TRUE, :reason, :trace_id
                    )
                    """
                ),
                {
                    "customer_id": customer_id,
                    "product_id": product["id"],
                    "customer_risk_level": customer_risk_level,
                    "product_risk_level": product["risk_level"],
                    "reason": (
                        f"产品风险等级 {product['risk_level']} "
                        f"不高于客户等级 {customer_risk_level}"
                    ),
                    "trace_id": trace_id,
                },
            )
