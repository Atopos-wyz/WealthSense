"""客户画像及画像评估 DAO。"""

from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.dao.mysql.json_utils import decode_json, encode_json


PROFILE_MUTABLE_COLUMNS = frozenset(
    {
        "investment_experience",
        "annual_income_range",
        "product_preference",
    }
)


class ProfileDAO:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, customer_id: int) -> dict[str, Any] | None:
        result = await self.session.execute(
            text(
                """
                SELECT customer_id, risk_level, investment_experience,
                       annual_income_range, total_assets, asset_allocation,
                       product_preference, confidence_score,
                       create_time, update_time
                FROM fin_customer_profile
                WHERE customer_id = :customer_id
                """
            ),
            {"customer_id": customer_id},
        )
        row = result.mappings().first()
        if row is None:
            return None
        profile = dict(row)
        profile["asset_allocation"] = decode_json(
            profile["asset_allocation"],
            {},
        )
        profile["product_preference"] = decode_json(
            profile["product_preference"],
            {},
        )
        return profile

    async def upsert(self, profile: dict[str, Any]) -> None:
        await self.session.execute(
            text(
                """
                INSERT INTO fin_customer_profile (
                    customer_id,
                    risk_level,
                    investment_experience,
                    annual_income_range,
                    total_assets,
                    asset_allocation,
                    product_preference,
                    confidence_score
                ) VALUES (
                    :customer_id,
                    :risk_level,
                    :investment_experience,
                    :annual_income_range,
                    :total_assets,
                    CAST(:asset_allocation AS JSON),
                    CAST(:product_preference AS JSON),
                    :confidence_score
                )
                ON DUPLICATE KEY UPDATE
                    risk_level = VALUES(risk_level),
                    investment_experience = VALUES(investment_experience),
                    annual_income_range = VALUES(annual_income_range),
                    total_assets = VALUES(total_assets),
                    asset_allocation = VALUES(asset_allocation),
                    product_preference = VALUES(product_preference),
                    confidence_score = VALUES(confidence_score)
                """
            ),
            {
                **profile,
                "asset_allocation": encode_json(profile["asset_allocation"]),
                "product_preference": encode_json(
                    profile["product_preference"]
                ),
            },
        )

    async def upsert_risk_level(
        self,
        customer_id: int,
        risk_level: str,
        confidence_score: Decimal,
    ) -> None:
        await self.session.execute(
            text(
                """
                INSERT INTO fin_customer_profile (
                    customer_id,
                    risk_level,
                    confidence_score
                ) VALUES (
                    :customer_id,
                    :risk_level,
                    :confidence_score
                )
                ON DUPLICATE KEY UPDATE
                    risk_level = VALUES(risk_level),
                    confidence_score = GREATEST(
                        confidence_score,
                        VALUES(confidence_score)
                    )
                """
            ),
            {
                "customer_id": customer_id,
                "risk_level": risk_level,
                "confidence_score": confidence_score,
            },
        )

    async def update_field(
        self,
        customer_id: int,
        field_name: str,
        value: Any,
    ) -> None:
        if field_name not in PROFILE_MUTABLE_COLUMNS:
            raise ValueError(f"禁止更新画像字段: {field_name}")
        parameter = value
        expression = f":{field_name}"
        if field_name == "product_preference":
            parameter = encode_json(value)
            expression = f"CAST(:{field_name} AS JSON)"
        await self.session.execute(
            text(
                f"""
                UPDATE fin_customer_profile
                SET {field_name} = {expression}
                WHERE customer_id = :customer_id
                """
            ),
            {
                "customer_id": customer_id,
                field_name: parameter,
            },
        )

    async def insert_evaluation(self, evaluation: dict[str, Any]) -> None:
        await self.session.execute(
            text(
                """
                INSERT INTO fin_profile_evaluation (
                    evaluation_no,
                    customer_id,
                    d1_score,
                    d2_score,
                    d3_score,
                    d4_score,
                    total_score,
                    official_risk_level,
                    model_risk_level,
                    effective_risk_level,
                    assessment_id,
                    score_detail,
                    rule_version,
                    trigger_type,
                    trigger_id
                ) VALUES (
                    :evaluation_no,
                    :customer_id,
                    :d1_score,
                    :d2_score,
                    :d3_score,
                    :d4_score,
                    :total_score,
                    :official_risk_level,
                    :model_risk_level,
                    :effective_risk_level,
                    :assessment_id,
                    CAST(:score_detail AS JSON),
                    :rule_version,
                    :trigger_type,
                    :trigger_id
                )
                """
            ),
            {
                **evaluation,
                "score_detail": encode_json(evaluation["score_detail"]),
            },
        )

    async def get_evaluation_by_trigger(
        self,
        trigger_id: str,
    ) -> dict[str, Any] | None:
        result = await self.session.execute(
            text(
                """
                SELECT *
                FROM fin_profile_evaluation
                WHERE trigger_id = :trigger_id
                LIMIT 1
                """
            ),
            {"trigger_id": trigger_id},
        )
        row = result.mappings().first()
        return self._evaluation_row(row)

    async def get_latest_evaluation(
        self,
        customer_id: int,
    ) -> dict[str, Any] | None:
        result = await self.session.execute(
            text(
                """
                SELECT *
                FROM fin_profile_evaluation
                WHERE customer_id = :customer_id
                ORDER BY create_time DESC, id DESC
                LIMIT 1
                """
            ),
            {"customer_id": customer_id},
        )
        return self._evaluation_row(result.mappings().first())

    async def list_evaluations(
        self,
        customer_id: int,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        result = await self.session.execute(
            text(
                """
                SELECT *
                FROM fin_profile_evaluation
                WHERE customer_id = :customer_id
                ORDER BY create_time DESC, id DESC
                LIMIT :limit
                """
            ),
            {"customer_id": customer_id, "limit": limit},
        )
        return [
            self._evaluation_row(row)
            for row in result.mappings().all()
        ]

    async def get_latest_applied_field_audit(
        self,
        customer_id: int,
        field_name: str,
    ) -> dict[str, Any] | None:
        result = await self.session.execute(
            text(
                """
                SELECT *
                FROM fin_profile_field_audit
                WHERE customer_id = :customer_id
                  AND field_name = :field_name
                  AND resolution = 'APPLIED'
                ORDER BY create_time DESC, id DESC
                LIMIT 1
                """
            ),
            {
                "customer_id": customer_id,
                "field_name": field_name,
            },
        )
        row = result.mappings().first()
        return dict(row) if row else None

    async def insert_field_audit(self, audit: dict[str, Any]) -> None:
        await self.session.execute(
            text(
                """
                INSERT INTO fin_profile_field_audit (
                    customer_id,
                    field_name,
                    old_value,
                    new_value,
                    old_source,
                    new_source,
                    old_confidence,
                    new_confidence,
                    resolution,
                    trigger_id
                ) VALUES (
                    :customer_id,
                    :field_name,
                    CAST(:old_value AS JSON),
                    CAST(:new_value AS JSON),
                    :old_source,
                    :new_source,
                    :old_confidence,
                    :new_confidence,
                    :resolution,
                    :trigger_id
                )
                """
            ),
            {
                **audit,
                "old_value": (
                    None
                    if audit["old_value"] is None
                    else encode_json(audit["old_value"])
                ),
                "new_value": encode_json(audit["new_value"]),
            },
        )

    @staticmethod
    def _evaluation_row(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        evaluation = dict(row)
        evaluation["score_detail"] = decode_json(
            evaluation["score_detail"],
            {},
        )
        return evaluation
