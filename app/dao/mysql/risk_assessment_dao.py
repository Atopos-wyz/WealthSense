"""风险评估与适当性检查 DAO。"""

from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.dao.mysql.json_utils import decode_json, encode_json


class RiskAssessmentDAO:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def insert(self, assessment: dict[str, Any]) -> int:
        result = await self.session.execute(
            text(
                """
                INSERT INTO fin_risk_assessment (
                    assessment_no,
                    customer_id,
                    assessment_date,
                    total_score,
                    risk_level,
                    answers,
                    assessor_type,
                    valid_until
                ) VALUES (
                    :assessment_no,
                    :customer_id,
                    :assessment_date,
                    :total_score,
                    :risk_level,
                    CAST(:answers AS JSON),
                    :assessor_type,
                    :valid_until
                )
                """
            ),
            {
                **assessment,
                "answers": encode_json(assessment["answers"]),
            },
        )
        return int(result.lastrowid)

    async def get_latest(
        self,
        customer_id: int,
        valid_only: bool = False,
    ) -> dict[str, Any] | None:
        valid_clause = "AND valid_until >= CURRENT_DATE" if valid_only else ""
        result = await self.session.execute(
            text(
                f"""
                SELECT *
                FROM fin_risk_assessment
                WHERE customer_id = :customer_id
                  {valid_clause}
                ORDER BY assessment_date DESC, id DESC
                LIMIT 1
                """
            ),
            {"customer_id": customer_id},
        )
        row = result.mappings().first()
        return self._assessment_row(row)

    async def list_history(
        self,
        customer_id: int,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        result = await self.session.execute(
            text(
                """
                SELECT id, assessment_no, customer_id, assessment_date,
                       total_score, risk_level, answers, assessor_type,
                       valid_until
                FROM fin_risk_assessment
                WHERE customer_id = :customer_id
                ORDER BY assessment_date DESC, id DESC
                LIMIT :limit
                """
            ),
            {"customer_id": customer_id, "limit": limit},
        )
        return [
            self._assessment_row(row)
            for row in result.mappings().all()
        ]

    async def get_product(self, product_id: int) -> dict[str, Any] | None:
        result = await self.session.execute(
            text(
                """
                SELECT id, product_code, product_name, product_type,
                       risk_level, status
                FROM fin_product
                WHERE id = :product_id
                """
            ),
            {"product_id": product_id},
        )
        row = result.mappings().first()
        return dict(row) if row else None

    async def insert_suitability_check(self, check: dict[str, Any]) -> None:
        await self.session.execute(
            text(
                """
                INSERT INTO fin_suitability_check (
                    customer_id,
                    product_id,
                    customer_risk_level,
                    product_risk_level,
                    allowed,
                    reason,
                    trace_id
                ) VALUES (
                    :customer_id,
                    :product_id,
                    :customer_risk_level,
                    :product_risk_level,
                    :allowed,
                    :reason,
                    :trace_id
                )
                """
            ),
            check,
        )

    @staticmethod
    def _assessment_row(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        assessment = dict(row)
        if "answers" in assessment:
            assessment["answers"] = decode_json(
                assessment["answers"],
                [],
            )
        assessment["expired"] = assessment["valid_until"] < date.today()
        return assessment
