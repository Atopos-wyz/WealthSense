"""云端 MySQL DAO 冒烟测试。

默认跳过。显式设置 RUN_CLOUD_INTEGRATION=1 和临时 SSH 密码环境变量后运行。
所有测试数据都在事务中回滚。
"""

import os
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.dao.mysql.cloud_init_schema import cloud_mysql_tunnel
from app.dao.mysql.init_schema import get_database_url
from app.dao.mysql.profile_dao import ProfileDAO
from app.dao.mysql.risk_assessment_dao import RiskAssessmentDAO


@unittest.skipUnless(
    os.getenv("RUN_CLOUD_INTEGRATION") == "1",
    "需要显式启用云端集成测试",
)
class MysqlDaoIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_profile_and_risk_dao_sql(self) -> None:
        with cloud_mysql_tunnel() as port:
            engine = create_async_engine(
                get_database_url(False, port),
                pool_pre_ping=False,
            )
            unique = uuid4().hex[:16]
            customer_id = int(f"9{uuid4().int % 10**16:016d}")
            product_id = customer_id + 1
            async with AsyncSession(engine, expire_on_commit=False) as session:
                transaction = await session.begin()
                try:
                    await session.execute(
                        text(
                            """
                            INSERT INTO sys_user (id, user_no, status)
                            VALUES (:id, :user_no, 'ACTIVE')
                            """
                        ),
                        {
                            "id": customer_id,
                            "user_no": f"smoke-user-{unique}",
                        },
                    )
                    await session.execute(
                        text(
                            """
                            INSERT INTO fin_product (
                                id, product_code, product_name,
                                product_type, risk_level, status
                            ) VALUES (
                                :id, :code, '集成测试产品',
                                '债券基金', 'R2', 'ACTIVE'
                            )
                            """
                        ),
                        {
                            "id": product_id,
                            "code": f"SMOKE-{unique}",
                        },
                    )

                    profile_dao = ProfileDAO(session)
                    assessment_dao = RiskAssessmentDAO(session)
                    await profile_dao.upsert(
                        {
                            "customer_id": customer_id,
                            "risk_level": "C3",
                            "investment_experience": "3-5年",
                            "annual_income_range": "30-50万元",
                            "total_assets": Decimal("500000"),
                            "asset_allocation": {"债券基金": 100},
                            "product_preference": {"基金": ["债券型"]},
                            "confidence_score": Decimal("0.90"),
                        }
                    )
                    now = datetime.now().replace(microsecond=0)
                    assessment_id = await assessment_dao.insert(
                        {
                            "assessment_no": f"SMOKE-RA-{unique}",
                            "customer_id": customer_id,
                            "assessment_date": now,
                            "total_score": Decimal("50"),
                            "risk_level": "C3",
                            "answers": [{"q": 1, "a": "B", "score": 33}],
                            "assessor_type": "AI评估",
                            "valid_until": date.today() + timedelta(days=365),
                        }
                    )
                    await profile_dao.insert_evaluation(
                        {
                            "evaluation_no": f"SMOKE-PE-{unique}",
                            "customer_id": customer_id,
                            "d1_score": Decimal("20"),
                            "d2_score": Decimal("15"),
                            "d3_score": Decimal("15"),
                            "d4_score": Decimal("20"),
                            "total_score": Decimal("70"),
                            "official_risk_level": "C3",
                            "model_risk_level": "C4",
                            "effective_risk_level": "C3",
                            "assessment_id": assessment_id,
                            "score_detail": {"smoke_test": True},
                            "rule_version": "TEST",
                            "trigger_type": "TEST",
                            "trigger_id": f"SMOKE-{unique}",
                        }
                    )
                    await profile_dao.insert_field_audit(
                        {
                            "customer_id": customer_id,
                            "field_name": "product_preference",
                            "old_value": None,
                            "new_value": {"基金": ["债券型"]},
                            "old_source": None,
                            "new_source": "USER_CONFIRMED",
                            "old_confidence": None,
                            "new_confidence": Decimal("0.80"),
                            "resolution": "APPLIED",
                            "trigger_id": f"SMOKE-{unique}",
                        }
                    )
                    await assessment_dao.insert_suitability_check(
                        {
                            "customer_id": customer_id,
                            "product_id": product_id,
                            "customer_risk_level": "C3",
                            "product_risk_level": "R2",
                            "allowed": True,
                            "reason": "集成测试",
                            "trace_id": f"SMOKE-{unique}",
                        }
                    )

                    profile = await profile_dao.get(customer_id)
                    latest = await assessment_dao.get_latest(
                        customer_id,
                        valid_only=True,
                    )
                    self.assertIsNotNone(profile)
                    self.assertIsNotNone(latest)
                    self.assertEqual(profile["risk_level"], "C3")
                finally:
                    await transaction.rollback()
            await engine.dispose()
