"""系统健康检查接口。"""

from fastapi import APIRouter, Depends

from app.dao import DatabaseManager, get_database_manager
from app.models.schemas import ApiResponse
from app.view.response import success_response

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health", response_model=ApiResponse[dict[str, bool]])
async def health(
    manager: DatabaseManager = Depends(get_database_manager),
) -> ApiResponse[dict[str, bool]]:
    return success_response(dict(await manager.health_check()))
