"""风险评估 Controller。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import get_session
from app.models.error_codes import ErrorCode, get_error_definition
from app.models.schemas import ApiResponse
from app.models.schemas.risk import (
    AssessmentHistoryItem,
    AssessmentResult,
    AssessmentSubmitRequest,
    QuestionnaireResponse,
    SuitabilityCheckRequest,
    SuitabilityCheckResult,
)
from app.service.risk.questionnaire import get_questionnaire
from app.service.risk.risk_assessment_service import RiskAssessmentService
from app.utils.logger import get_trace_id
from app.view.response import success_response


router = APIRouter(prefix="/api/risk", tags=["风险评估"])


def get_risk_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RiskAssessmentService:
    return RiskAssessmentService(session)


@router.get(
    "/questionnaire",
    response_model=ApiResponse[QuestionnaireResponse],
    summary="获取16道风险评估问卷",
)
async def questionnaire(
) -> ApiResponse[QuestionnaireResponse]:
    return success_response(get_questionnaire())


@router.post(
    "/assessment",
    response_model=ApiResponse[AssessmentResult],
    summary="提交风险评估",
)
async def submit_assessment(
    payload: AssessmentSubmitRequest,
    service: Annotated[RiskAssessmentService, Depends(get_risk_service)],
) -> ApiResponse[AssessmentResult]:
    return success_response(await service.submit(payload))


@router.get(
    "/assessment/{customer_id}/history",
    response_model=ApiResponse[list[AssessmentHistoryItem]],
    summary="查询风险评估历史",
)
async def assessment_history(
    customer_id: int,
    service: Annotated[RiskAssessmentService, Depends(get_risk_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ApiResponse[list[AssessmentHistoryItem]]:
    return success_response(
        await service.history(customer_id, limit),
    )


@router.post(
    "/suitability-check",
    response_model=ApiResponse[SuitabilityCheckResult],
    summary="检查客户与产品适当性",
)
async def suitability_check(
    payload: SuitabilityCheckRequest,
    service: Annotated[RiskAssessmentService, Depends(get_risk_service)],
) -> ApiResponse[SuitabilityCheckResult]:
    trace_id = get_trace_id()
    result = await service.suitability_check(
        payload,
        trace_id,
    )
    if result.allowed:
        return success_response(result, trace_id=trace_id)
    definition = get_error_definition(ErrorCode.SUITABILITY_MISMATCH)
    return ApiResponse[SuitabilityCheckResult](
        code=definition.code,
        message=definition.message,
        data=result,
        trace_id=trace_id,
    )
