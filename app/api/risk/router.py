"""风险评估 Controller。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import get_session
from app.models.schemas.common import ApiResponse
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
from app.utils.response import success


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
    request: Request,
) -> ApiResponse[QuestionnaireResponse]:
    return success(request, get_questionnaire())


@router.post(
    "/assessment",
    response_model=ApiResponse[AssessmentResult],
    summary="提交风险评估",
)
async def submit_assessment(
    payload: AssessmentSubmitRequest,
    request: Request,
    service: Annotated[RiskAssessmentService, Depends(get_risk_service)],
) -> ApiResponse[AssessmentResult]:
    return success(request, await service.submit(payload))


@router.get(
    "/assessment/{customer_id}/history",
    response_model=ApiResponse[list[AssessmentHistoryItem]],
    summary="查询风险评估历史",
)
async def assessment_history(
    customer_id: int,
    request: Request,
    service: Annotated[RiskAssessmentService, Depends(get_risk_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ApiResponse[list[AssessmentHistoryItem]]:
    return success(
        request,
        await service.history(customer_id, limit),
    )


@router.post(
    "/suitability-check",
    response_model=ApiResponse[SuitabilityCheckResult],
    summary="检查客户与产品适当性",
)
async def suitability_check(
    payload: SuitabilityCheckRequest,
    request: Request,
    service: Annotated[RiskAssessmentService, Depends(get_risk_service)],
) -> ApiResponse[SuitabilityCheckResult]:
    result = await service.suitability_check(
        payload,
        request.state.trace_id,
    )
    if result.allowed:
        return success(request, result)
    return ApiResponse[SuitabilityCheckResult](
        code=1005,
        message="适当性不匹配",
        data=result,
        trace_id=request.state.trace_id,
    )
