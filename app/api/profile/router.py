"""客户画像 Controller。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import get_session
from app.models.schemas.common import ApiResponse
from app.models.schemas.profile import (
    ProfileCreateRequest,
    ProfileEvaluationResponse,
    ProfileResponse,
    ProfileUpdateRequest,
    ProfileUpdateResult,
)
from app.models.schemas.risk import (
    AssessmentAnswersRequest,
    AssessmentHistoryItem,
    AssessmentResult,
    AssessmentSubmitRequest,
)
from app.service.profile.profile_service import ProfileService
from app.service.risk.risk_assessment_service import RiskAssessmentService
from app.utils.response import success


router = APIRouter(prefix="/api/profile", tags=["客户画像"])


def get_profile_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProfileService:
    return ProfileService(session)


def get_risk_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RiskAssessmentService:
    return RiskAssessmentService(session)


@router.post(
    "/create",
    response_model=ApiResponse[ProfileResponse],
    summary="创建或重建客户画像",
)
async def create_profile(
    payload: ProfileCreateRequest,
    request: Request,
    service: Annotated[ProfileService, Depends(get_profile_service)],
) -> ApiResponse[ProfileResponse]:
    return success(request, await service.create(payload))


@router.get(
    "/{customer_id}",
    response_model=ApiResponse[ProfileResponse],
    summary="获取客户画像",
)
async def get_profile(
    customer_id: int,
    request: Request,
    service: Annotated[ProfileService, Depends(get_profile_service)],
) -> ApiResponse[ProfileResponse]:
    return success(request, await service.get(customer_id))


@router.put(
    "/{customer_id}",
    response_model=ApiResponse[ProfileUpdateResult],
    summary="按字段权限和置信度更新客户画像",
)
async def update_profile(
    customer_id: int,
    payload: ProfileUpdateRequest,
    request: Request,
    service: Annotated[ProfileService, Depends(get_profile_service)],
) -> ApiResponse[ProfileUpdateResult]:
    return success(
        request,
        await service.update(customer_id, payload),
    )


@router.get(
    "/{customer_id}/evaluations/latest",
    response_model=ApiResponse[ProfileEvaluationResponse],
    summary="获取最新四维画像评估",
)
async def latest_profile_evaluation(
    customer_id: int,
    request: Request,
    service: Annotated[ProfileService, Depends(get_profile_service)],
) -> ApiResponse[ProfileEvaluationResponse]:
    return success(
        request,
        await service.latest_evaluation(customer_id),
    )


@router.get(
    "/{customer_id}/evaluations",
    response_model=ApiResponse[list[ProfileEvaluationResponse]],
    summary="获取四维画像评估历史",
)
async def profile_evaluation_history(
    customer_id: int,
    request: Request,
    service: Annotated[ProfileService, Depends(get_profile_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ApiResponse[list[ProfileEvaluationResponse]]:
    return success(
        request,
        await service.evaluation_history(customer_id, limit),
    )


@router.post(
    "/{customer_id}/assessment",
    response_model=ApiResponse[AssessmentResult],
    summary="为指定客户提交风险评估",
)
async def submit_customer_assessment(
    customer_id: int,
    payload: AssessmentAnswersRequest,
    request: Request,
    service: Annotated[RiskAssessmentService, Depends(get_risk_service)],
) -> ApiResponse[AssessmentResult]:
    submit_request = AssessmentSubmitRequest(
        customer_id=customer_id,
        answers=payload.answers,
        assessor_type=payload.assessor_type,
    )
    return success(request, await service.submit(submit_request))


@router.get(
    "/{customer_id}/assessment/history",
    response_model=ApiResponse[list[AssessmentHistoryItem]],
    summary="获取客户风险评估历史",
)
async def customer_assessment_history(
    customer_id: int,
    request: Request,
    service: Annotated[RiskAssessmentService, Depends(get_risk_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ApiResponse[list[AssessmentHistoryItem]]:
    return success(
        request,
        await service.history(customer_id, limit),
    )
