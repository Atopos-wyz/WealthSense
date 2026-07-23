from fastapi import APIRouter

from app.api.operation.dependencies import ContainerDependency, OperatorDependency
from app.models.schemas.operation import (
    CancelOperationRequest,
    ChatOperationRequest,
    ConfirmOperationRequest,
    OperationResponse,
    UpdateOperationRequest,
)
from app.utils.exceptions import (
    OperatorPermissionDeniedError as PermissionDeniedError,
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
    operator: OperatorDependency,
    container: ContainerDependency,
) -> OperationResponse:
    if body.confirmer_id != operator.operator_id:
        raise PermissionDeniedError(
            "OP_PERMISSION_DENIED",
            "确认人必须与当前登录身份一致",
        )
    await container.operation_service.authorize_access(operation_id, operator)
    return await container.operation_service.confirm(operation_id, body)


@router.patch("/{operation_id}/params", response_model=OperationResponse)
async def update_operation_parameters(
    operation_id: str,
    body: UpdateOperationRequest,
    operator: OperatorDependency,
    container: ContainerDependency,
) -> OperationResponse:
    if body.updated_by != operator.operator_id:
        raise PermissionDeniedError(
            "OP_PERMISSION_DENIED",
            "参数修改人必须与当前登录身份一致",
        )
    return await container.operation_service.update_parameters(
        operation_id,
        body,
        operator,
    )


@router.post("/{operation_id}/cancel", response_model=OperationResponse)
async def cancel_operation(
    operation_id: str,
    body: CancelOperationRequest,
    operator: OperatorDependency,
    container: ContainerDependency,
) -> OperationResponse:
    if body.cancelled_by != operator.operator_id:
        raise PermissionDeniedError(
            "OP_PERMISSION_DENIED",
            "取消人必须与当前登录身份一致",
        )
    await container.operation_service.authorize_access(operation_id, operator)
    return await container.operation_service.cancel(operation_id, body)


@router.get("/{operation_id}", response_model=OperationResponse)
async def get_operation(
    operation_id: str,
    request_id: str,
    operator: OperatorDependency,
    container: ContainerDependency,
) -> OperationResponse:
    await container.operation_service.authorize_access(operation_id, operator)
    return await container.operation_service.get_response(operation_id, request_id)


@router.post("/{operation_id}/reconcile", response_model=OperationResponse)
async def reconcile_operation(
    operation_id: str,
    request_id: str,
    operator: OperatorDependency,
    container: ContainerDependency,
) -> OperationResponse:
    await container.operation_service.authorize_access(operation_id, operator)
    return await container.operation_service.reconcile(operation_id, request_id)
