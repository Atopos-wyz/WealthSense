from decimal import Decimal
from typing import Any, Protocol

from app.models.schemas.common import OperationIntent


class MockOperationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class MockOperationTimeout(TimeoutError):
    pass


class OperationTool(Protocol):
    async def execute(
        self,
        intent: OperationIntent,
        operation_id: str,
        params: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]: ...

    async def get_status(self, operation_id: str) -> dict[str, Any] | None: ...


class OperationToolRegistry:
    """Mock implementation of all eight fixed business APIs."""

    def __init__(self) -> None:
        self.results: dict[str, dict[str, Any]] = {}
        self.idempotency_results: dict[str, dict[str, Any]] = {}

    async def execute(
        self,
        intent: OperationIntent,
        operation_id: str,
        params: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        if idempotency_key in self.idempotency_results:
            return dict(self.idempotency_results[idempotency_key])
        if params.get("simulate_timeout"):
            if params.get("eventual_success", True):
                result = self._build_result(intent, operation_id, params)
                self.results[operation_id] = dict(result)
                self.idempotency_results[idempotency_key] = dict(result)
            raise MockOperationTimeout("mock API timeout")
        if params.get("simulate_failure"):
            raise MockOperationError(
                "OP_MOCK_API_FAILED",
                "Mock业务接口执行失败",
            )
        if params.get("account_id") == "A_FROZEN":
            raise MockOperationError("OP_ACCOUNT_FROZEN", "账户已冻结")
        amount = params.get("amount")
        if amount is not None and Decimal(str(amount)) > Decimal("10000000"):
            raise MockOperationError("OP_LIMIT_EXCEEDED", "金额超过Mock接口限额")

        result = self._build_result(intent, operation_id, params)
        self.results[operation_id] = dict(result)
        self.idempotency_results[idempotency_key] = dict(result)
        return result

    @staticmethod
    def _build_result(
        intent: OperationIntent,
        operation_id: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "operation_id": operation_id,
            "action": intent.value,
            "status": "succeeded",
        }
        if intent in {
            OperationIntent.PURCHASE,
            OperationIntent.REDEEM,
            OperationIntent.TRANSFER,
        }:
            result["transaction_id"] = f"TX_{operation_id.removeprefix('OP_')}"
        elif intent == OperationIntent.CREATE_WORK_ORDER:
            result["work_order_id"] = f"WO_{operation_id.removeprefix('OP_')}"
        elif intent == OperationIntent.SUSPICIOUS_REPORT:
            result["report_id"] = f"SR_{operation_id.removeprefix('OP_')}"
        elif intent == OperationIntent.PRODUCT_QUERY:
            result["product"] = {
                "product_id": params["product_id"],
                "name": "Mock稳健产品",
                "status": "active",
                "net_value": "1.0234",
            }
        return result

    async def get_status(self, operation_id: str) -> dict[str, Any] | None:
        result = self.results.get(operation_id)
        return dict(result) if result else None
