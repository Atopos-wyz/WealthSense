from fastapi import APIRouter

from app.api.operation.dependencies import ContainerDependency, OperatorDependency
from app.models.schemas.operation import (
    CancelOperationRequest,
    ChatOperationRequest,
    ConfirmOperationRequest,
    OperationResponse,
)

router = APIRouter(prefix="/api/operation", tags=["business-operator"])


@router.post("/chat", response_model=OperationResponse)
async def create_operation(
    body: ChatOperationRequest,
    operator: OperatorDependency,
    container: ContainerDependency,
) -> OperationResponse:
    return await container.operator_agent.handle_chat(body, operator)


@router.post("/{operation_id}/confirm", response_model=OperationResponse)
async def confirm_operation(
    operation_id: str,
    body: ConfirmOperationRequest,
    container: ContainerDependency,
) -> OperationResponse:
    return await container.operation_service.confirm(operation_id, body)


@router.post("/{operation_id}/cancel", response_model=OperationResponse)
async def cancel_operation(
    operation_id: str,
    body: CancelOperationRequest,
    container: ContainerDependency,
) -> OperationResponse:
    return await container.operation_service.cancel(operation_id, body)


@router.get("/{operation_id}", response_model=OperationResponse)
async def get_operation(
    operation_id: str,
    request_id: str,
    container: ContainerDependency,
) -> OperationResponse:
    return await container.operation_service.get_response(operation_id, request_id)

