"""风险问卷提交、历史查询与适当性检查。"""

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.dao.mysql.profile_dao import ProfileDAO
from app.dao.mysql.risk_assessment_dao import RiskAssessmentDAO
from app.dao.mysql.user_dao import UserDAO
from app.dao.redis.profile_cache_dao import ProfileCacheDAO
from app.config.cache import get_redis_client
from app.models.schemas.common import RiskLevel
from app.models.schemas.profile import ProfileFacts
from app.models.schemas.risk import (
    AssessmentHistoryItem,
    AssessmentResult,
    AssessmentSubmitRequest,
    SuitabilityCheckRequest,
    SuitabilityCheckResult,
)
from app.service.risk.scoring import (
    RISK_LABELS,
    conservative_merge,
    score_answers,
)
from app.service.profile.score_engine import RULE_VERSION, evaluate_profile
from app.utils.exceptions import BusinessError


class RiskAssessmentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.user_dao = UserDAO(session)
        self.profile_dao = ProfileDAO(session)
        self.assessment_dao = RiskAssessmentDAO(session)
        self.cache_dao = ProfileCacheDAO(get_redis_client())

    async def submit(
        self,
        request: AssessmentSubmitRequest,
    ) -> AssessmentResult:
        if not await self.user_dao.exists(request.customer_id):
            raise BusinessError(404, "客户不存在", 404)

        total_score, official_level, scored_answers = score_answers(
            request.answers
        )
        now = datetime.now().replace(microsecond=0)
        valid_until = now.date() + timedelta(days=365)
        assessment_no = f"RA-{now:%Y%m%d}-{uuid4().hex[:16]}"
        assessment_id = await self.assessment_dao.insert(
            {
                "assessment_no": assessment_no,
                "customer_id": request.customer_id,
                "assessment_date": now,
                "total_score": total_score,
                "risk_level": official_level.value,
                "answers": [
                    item.model_dump(mode="json")
                    for item in scored_answers
                ],
                "assessor_type": request.assessor_type,
                "valid_until": valid_until,
            }
        )

        latest_evaluation = await self.profile_dao.get_latest_evaluation(
            request.customer_id
        )
        effective_level = official_level
        if latest_evaluation is not None:
            saved_facts = latest_evaluation["score_detail"].get(
                "profile_facts"
            )
            if saved_facts:
                rebuilt = evaluate_profile(
                    ProfileFacts.model_validate(saved_facts),
                    official_level,
                    total_score,
                )
                effective_level = rebuilt.effective_level
                await self.profile_dao.insert_evaluation(
                    {
                        "evaluation_no": f"PE-{uuid4().hex}",
                        "customer_id": request.customer_id,
                        "d1_score": rebuilt.d1,
                        "d2_score": rebuilt.d2,
                        "d3_score": rebuilt.d3,
                        "d4_score": rebuilt.d4,
                        "total_score": rebuilt.total,
                        "official_risk_level": official_level.value,
                        "model_risk_level": rebuilt.model_level.value,
                        "effective_risk_level": effective_level.value,
                        "assessment_id": assessment_id,
                        "score_detail": {
                            **rebuilt.score_detail,
                            "profile_facts": saved_facts,
                        },
                        "rule_version": RULE_VERSION,
                        "trigger_type": "ASSESSMENT_COMPLETED",
                        "trigger_id": assessment_no,
                    }
                )
            else:
                effective_level = conservative_merge(
                    official_level,
                    RiskLevel(latest_evaluation["model_risk_level"]),
                )
        await self.profile_dao.upsert_risk_level(
            request.customer_id,
            effective_level.value,
            Decimal("0.90"),
        )
        await self.session.commit()
        await self.cache_dao.delete(request.customer_id)
        return AssessmentResult(
            assessment_id=assessment_id,
            assessment_no=assessment_no,
            customer_id=request.customer_id,
            total_score=total_score,
            risk_level=official_level,
            risk_label=RISK_LABELS[official_level],
            answers=scored_answers,
            assessment_date=now,
            valid_until=valid_until,
            confidence_score=Decimal("0.90"),
        )

    async def history(
        self,
        customer_id: int,
        limit: int = 20,
    ) -> list[AssessmentHistoryItem]:
        rows = await self.assessment_dao.list_history(customer_id, limit)
        return [
            AssessmentHistoryItem(
                assessment_id=row["id"],
                assessment_no=row["assessment_no"],
                total_score=row["total_score"],
                risk_level=RiskLevel(row["risk_level"]),
                assessor_type=row["assessor_type"],
                assessment_date=row["assessment_date"],
                valid_until=row["valid_until"],
                expired=row["expired"],
            )
            for row in rows
        ]

    async def suitability_check(
        self,
        request: SuitabilityCheckRequest,
        trace_id: str,
    ) -> SuitabilityCheckResult:
        profile = await self.profile_dao.get(request.customer_id)
        if profile is None or profile["risk_level"] is None:
            raise BusinessError(404, "客户画像或风险等级不存在", 404)
        product = await self.assessment_dao.get_product(request.product_id)
        if product is None:
            raise BusinessError(404, "产品不存在", 404)
        if product["risk_level"] not in {f"R{i}" for i in range(1, 6)}:
            raise BusinessError(400, "产品风险等级配置不合法")

        customer_level = RiskLevel(profile["risk_level"])
        maximum_rank = int(customer_level[1])
        evaluation = await self.profile_dao.get_latest_evaluation(
            request.customer_id
        )
        if evaluation is not None:
            restriction = (
                evaluation["score_detail"]
                .get("restrictions", {})
                .get("maximum_product_risk")
            )
            if restriction in {f"R{i}" for i in range(1, 6)}:
                maximum_rank = min(maximum_rank, int(restriction[1]))

        latest_valid_assessment = await self.assessment_dao.get_latest(
            request.customer_id,
            valid_only=True,
        )
        product_rank = int(product["risk_level"][1])
        product_available = product["status"] in {"ACTIVE", "在售"}
        if latest_valid_assessment is None:
            allowed = False
            reason = "风险评估不存在或已过期，请重新评估"
        elif not product_available:
            allowed = False
            reason = "产品当前不可销售"
        elif product_rank > maximum_rank:
            allowed = False
            reason = (
                f"客户最高可匹配R{maximum_rank}，"
                f"目标产品为{product['risk_level']}"
            )
        else:
            allowed = True
            reason = "客户风险承受等级与产品风险等级匹配"

        await self.assessment_dao.insert_suitability_check(
            {
                "customer_id": request.customer_id,
                "product_id": request.product_id,
                "customer_risk_level": customer_level.value,
                "product_risk_level": product["risk_level"],
                "allowed": allowed,
                "reason": reason,
                "trace_id": trace_id,
            }
        )
        await self.session.commit()
        return SuitabilityCheckResult(
            customer_id=request.customer_id,
            product_id=request.product_id,
            customer_risk_level=customer_level,
            product_risk_level=product["risk_level"],
            maximum_allowed_product_risk=f"R{maximum_rank}",
            allowed=allowed,
            warning_code=None if allowed else 1005,
            reason=reason,
        )
