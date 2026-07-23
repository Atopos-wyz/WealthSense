"""客户画像创建、查询、更新与冲突审计。"""

from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.dao.mysql.profile_dao import ProfileDAO
from app.dao.mysql.risk_assessment_dao import RiskAssessmentDAO
from app.dao.mysql.user_dao import UserDAO
from app.dao.redis.profile_cache_dao import ProfileCacheDAO
from app.config.cache import get_redis_client
from app.event.publisher import RedisEventPublisher
from app.models.schemas.common import (
    SOURCE_CONFIDENCE,
    DataSource,
    RiskLevel,
)
from app.models.error_codes import ErrorCode
from app.models.schemas.event import AgentEvent, AgentEventType, AgentType
from app.models.schemas.profile import (
    FieldUpdateResult,
    ProfileCreateRequest,
    ProfileEvaluationResponse,
    ProfileResponse,
    ProfileUpdateRequest,
    ProfileUpdateResult,
)
from app.service.profile.score_engine import (
    RULE_VERSION,
    annual_income_range,
    evaluate_profile,
    investment_experience_range,
)
from app.utils.exceptions import (
    AppException,
    ConflictError,
    ResourceNotFoundError,
)
from app.utils.logger import get_trace_id


FIELD_AUTHORITIES: dict[str, frozenset[DataSource]] = {
    "investment_experience": frozenset(
        {DataSource.KYC, DataSource.MANUAL_VERIFIED}
    ),
    "annual_income_range": frozenset({DataSource.KYC}),
    "product_preference": frozenset(
        {DataSource.USER_CONFIRMED, DataSource.MANUAL_VERIFIED}
    ),
}


class ProfileService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        event_publisher: RedisEventPublisher | None = None,
    ) -> None:
        self.session = session
        self.user_dao = UserDAO(session)
        self.profile_dao = ProfileDAO(session)
        self.assessment_dao = RiskAssessmentDAO(session)
        self.cache_dao = ProfileCacheDAO(get_redis_client())
        self.event_publisher = event_publisher or RedisEventPublisher()

    async def create(self, request: ProfileCreateRequest) -> ProfileResponse:
        if not await self.user_dao.exists(request.customer_id):
            raise ResourceNotFoundError("客户")

        existing_evaluation = await self.profile_dao.get_evaluation_by_trigger(
            request.trigger_id
        )
        if existing_evaluation is not None:
            if existing_evaluation["customer_id"] != request.customer_id:
                raise ConflictError("trigger_id已被其他客户使用")
            return await self.get(request.customer_id)

        assessment = await self.assessment_dao.get_latest(
            request.customer_id,
            valid_only=True,
        )
        if assessment is None:
            latest = await self.assessment_dao.get_latest(request.customer_id)
            message = (
                "风险评估已过期，请重新完成风险评估"
                if latest is not None
                else "创建画像前必须先完成风险评估"
            )
            raise AppException(
                ErrorCode.INVALID_ARGUMENT,
                message=message,
            )

        score = evaluate_profile(
            facts=request.facts,
            official_level=RiskLevel(assessment["risk_level"]),
            questionnaire_score=Decimal(assessment["total_score"]),
        )
        source_confidence = Decimal(
            str(SOURCE_CONFIDENCE[request.source])
        )
        confidence_score = (
            (
                Decimal("0.90")
                + source_confidence
                + source_confidence
            )
            / Decimal("3")
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        profile_data = {
            "customer_id": request.customer_id,
            "risk_level": score.effective_level.value,
            "investment_experience": investment_experience_range(
                request.facts.investment_years
            ),
            "annual_income_range": annual_income_range(
                request.facts.annual_income
            ),
            "total_assets": request.facts.investable_assets,
            "asset_allocation": request.asset_allocation,
            "product_preference": request.product_preference,
            "confidence_score": confidence_score,
        }
        await self.profile_dao.upsert(profile_data)

        evaluation = {
            "evaluation_no": f"PE-{uuid4().hex}",
            "customer_id": request.customer_id,
            "d1_score": score.d1,
            "d2_score": score.d2,
            "d3_score": score.d3,
            "d4_score": score.d4,
            "total_score": score.total,
            "official_risk_level": score.official_level.value,
            "model_risk_level": score.model_level.value,
            "effective_risk_level": score.effective_level.value,
            "assessment_id": assessment["id"],
            "score_detail": {
                **score.score_detail,
                "profile_facts": request.facts.model_dump(mode="json"),
                "conversation_candidate_received": bool(
                    request.conversation_text
                ),
            },
            "rule_version": RULE_VERSION,
            "trigger_type": request.trigger_type,
            "trigger_id": request.trigger_id,
        }
        await self.profile_dao.insert_evaluation(evaluation)

        initial_fields = {
            "investment_experience": profile_data["investment_experience"],
            "annual_income_range": profile_data["annual_income_range"],
            "product_preference": profile_data["product_preference"],
        }
        for field_name, value in initial_fields.items():
            await self.profile_dao.insert_field_audit(
                {
                    "customer_id": request.customer_id,
                    "field_name": field_name,
                    "old_value": None,
                    "new_value": value,
                    "old_source": None,
                    "new_source": request.source.value,
                    "old_confidence": None,
                    "new_confidence": source_confidence,
                    "resolution": "APPLIED",
                    "trigger_id": request.trigger_id,
                }
            )

        await self.session.commit()
        await self.cache_dao.delete(request.customer_id)
        response = await self.get(request.customer_id)
        await self._publish_profile_updated(
            customer_id=request.customer_id,
            trigger_id=request.trigger_id,
            changed_fields=[
                "risk_level",
                "investment_experience",
                "annual_income_range",
                "total_assets",
                "asset_allocation",
                "product_preference",
            ],
        )
        return response

    async def get(self, customer_id: int) -> ProfileResponse:
        cached = await self.cache_dao.get(customer_id)
        if cached is not None:
            return ProfileResponse.model_validate(cached)
        profile = await self.profile_dao.get(customer_id)
        if profile is None:
            raise ResourceNotFoundError("客户画像")
        response = ProfileResponse.model_validate(profile)
        await self.cache_dao.set(
            customer_id,
            response.model_dump(mode="json"),
        )
        return response

    async def update(
        self,
        customer_id: int,
        request: ProfileUpdateRequest,
    ) -> ProfileUpdateResult:
        current = await self.profile_dao.get(customer_id)
        if current is None:
            raise ResourceNotFoundError("客户画像")

        incoming_fields = request.model_dump(
            exclude={"source", "trigger_id"},
            exclude_none=True,
            mode="json",
        )
        field_results: list[FieldUpdateResult] = []
        new_confidence = Decimal(
            str(SOURCE_CONFIDENCE[request.source])
        )
        for field_name, new_value in incoming_fields.items():
            old_value = current[field_name]
            latest_audit = (
                await self.profile_dao.get_latest_applied_field_audit(
                    customer_id,
                    field_name,
                )
            )
            old_source = (
                latest_audit["new_source"] if latest_audit else None
            )
            old_confidence = (
                Decimal(latest_audit["new_confidence"])
                if latest_audit
                else None
            )
            authorized = request.source in FIELD_AUTHORITIES[field_name]
            if not authorized:
                resolution = (
                    "CANDIDATE"
                    if request.source
                    in {
                        DataSource.AI_CONVERSATION,
                        DataSource.USER_DECLARED,
                    }
                    else "REJECTED"
                )
                reason = "来源无权直接修改该字段，已保留候选或审计记录"
            elif (
                old_source is not None
                and old_source != request.source.value
                and old_confidence is not None
                and new_confidence < old_confidence
            ):
                resolution = "REJECTED"
                reason = "新来源置信度低于现有权威来源"
            else:
                resolution = "APPLIED"
                reason = "字段权限及置信度检查通过"
                await self.profile_dao.update_field(
                    customer_id,
                    field_name,
                    new_value,
                )
                current[field_name] = new_value

            await self.profile_dao.insert_field_audit(
                {
                    "customer_id": customer_id,
                    "field_name": field_name,
                    "old_value": old_value,
                    "new_value": new_value,
                    "old_source": old_source,
                    "new_source": request.source.value,
                    "old_confidence": old_confidence,
                    "new_confidence": new_confidence,
                    "resolution": resolution,
                    "trigger_id": request.trigger_id,
                }
            )
            field_results.append(
                FieldUpdateResult(
                    field_name=field_name,
                    resolution=resolution,
                    reason=reason,
                )
            )

        await self.session.commit()
        await self.cache_dao.delete(customer_id)
        result = ProfileUpdateResult(
            profile=await self.get(customer_id),
            fields=field_results,
        )
        await self._publish_profile_updated(
            customer_id=customer_id,
            trigger_id=request.trigger_id,
            changed_fields=[
                field.field_name
                for field in field_results
                if field.resolution == "APPLIED"
            ],
        )
        return result

    async def latest_evaluation(
        self,
        customer_id: int,
    ) -> ProfileEvaluationResponse:
        evaluation = await self.profile_dao.get_latest_evaluation(customer_id)
        if evaluation is None:
            raise ResourceNotFoundError("客户画像评估记录")
        return ProfileEvaluationResponse.model_validate(evaluation)

    async def evaluation_history(
        self,
        customer_id: int,
        limit: int = 20,
    ) -> list[ProfileEvaluationResponse]:
        rows = await self.profile_dao.list_evaluations(customer_id, limit)
        return [
            ProfileEvaluationResponse.model_validate(row)
            for row in rows
        ]

    async def _publish_profile_updated(
        self,
        *,
        customer_id: int,
        trigger_id: str,
        changed_fields: list[str],
    ) -> None:
        await self.event_publisher.publish(
            AgentEvent(
                event_type=AgentEventType.PROFILE_UPDATED,
                source_agent=AgentType.SYSTEM,
                target_agents=[AgentType.ADVISOR, AgentType.RISK],
                payload={
                    "changed_fields": changed_fields,
                    "trigger_id": trigger_id,
                },
                trace_id=get_trace_id(),
                customer_id=customer_id,
                correlation_id=trigger_id,
                deduplication_key=(
                    f"{AgentEventType.PROFILE_UPDATED.value}:"
                    f"{trigger_id}"
                ),
            )
        )
