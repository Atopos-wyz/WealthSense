from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.dao.mysql.mock_business_repository import (
    MockBusinessError,
    MockBusinessPending,
    MockBusinessRepository,
)
from app.models.schemas.common import OperationIntent
from app.tool.operation.registry import MockOperationError, MockOperationTimeout


class DatabaseOperationToolRegistry:
    """Stable tool facade backed by the server-side mock repository."""

    def __init__(self, repository: MockBusinessRepository) -> None:
        self.repository = repository

    async def execute(
        self,
        intent: OperationIntent,
        operation_id: str,
        params: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        try:
            result = await self.repository.execute(
                intent,
                operation_id,
                params,
                idempotency_key,
            )
        except MockBusinessPending as exc:
            raise MockOperationTimeout("mock API result is pending") from exc
        except MockBusinessError as exc:
            raise MockOperationError(exc.code, exc.message) from exc
        except KeyError as exc:
            raise MockOperationError(
                "OP_PARAM_MISSING",
                f"缺少业务参数：{exc.args[0]}",
            ) from exc
        except (ArithmeticError, TypeError, ValueError) as exc:
            raise MockOperationError(
                "OP_PARAM_INVALID",
                "业务参数格式不正确",
            ) from exc
        except SQLAlchemyError as exc:
            raise MockOperationError(
                "OP_MOCK_API_FAILED",
                "数据库 Mock 暂时不可用",
            ) from exc

        if params.get("simulate_timeout"):
            raise MockOperationTimeout("mock API timeout")
        return result

    async def get_status(self, operation_id: str) -> dict[str, Any] | None:
        try:
            return await self.repository.get_status(operation_id)
        except SQLAlchemyError as exc:
            raise MockOperationError(
                "OP_MOCK_API_FAILED",
                "数据库 Mock 状态查询失败",
            ) from exc
