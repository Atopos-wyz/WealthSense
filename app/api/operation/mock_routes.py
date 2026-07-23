from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.operation.dependencies import ContainerDependency
from app.models.schemas.common import OperationIntent
from app.tool.operation.registry import MockOperationError, MockOperationTimeout

router = APIRouter(prefix="/mock", tags=["mock-business-api"])


class MockExecuteRequest(BaseModel):
    operation_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str


@router.post("/operations/{intent}")
async def execute_mock_operation(
    intent: OperationIntent,
    body: MockExecuteRequest,
    container: ContainerDependency,
) -> dict[str, Any]:
    try:
        return await container.tool_registry.execute(
            intent,
            body.operation_id,
            body.params,
            body.idempotency_key,
        )
    except MockOperationTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except MockOperationError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@router.get("/operations/{operation_id}/status")
async def get_mock_operation_status(
    operation_id: str,
    container: ContainerDependency,
) -> dict[str, Any]:
    result = await container.tool_registry.get_status(operation_id)
    if not result:
        raise HTTPException(status_code=404, detail="operation not found")
    return result

