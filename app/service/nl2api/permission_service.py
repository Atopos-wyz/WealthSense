from app.models.schemas.common import OperationIntent
from app.models.schemas.operation import OperatorContext
from app.utils.exceptions import PermissionDeniedError


ROLE_PERMISSIONS: dict[str, set[OperationIntent]] = {
    "customer": {
        OperationIntent.PURCHASE,
        OperationIntent.REDEEM,
        OperationIntent.TRANSFER,
        OperationIntent.RISK_REASSESSMENT,
        OperationIntent.UPDATE_PROFILE,
        OperationIntent.PRODUCT_QUERY,
        OperationIntent.CREATE_WORK_ORDER,
    },
    "advisor": {
        OperationIntent.PURCHASE,
        OperationIntent.REDEEM,
        OperationIntent.RISK_REASSESSMENT,
        OperationIntent.PRODUCT_QUERY,
    },
    "customer_manager": {
        OperationIntent.UPDATE_PROFILE,
        OperationIntent.PRODUCT_QUERY,
        OperationIntent.CREATE_WORK_ORDER,
    },
    "risk_officer": {
        OperationIntent.PRODUCT_QUERY,
        OperationIntent.SUSPICIOUS_REPORT,
        OperationIntent.CREATE_WORK_ORDER,
    },
    "system": set(OperationIntent) - {OperationIntent.UNKNOWN},
}


def check_permission(
    operator: OperatorContext,
    intent: OperationIntent,
    customer_id: str | None,
) -> None:
    allowed = ROLE_PERMISSIONS.get(operator.role, set())
    if intent not in allowed:
        raise PermissionDeniedError(
            "OP_PERMISSION_DENIED",
            f"role {operator.role} cannot perform {intent.value}",
        )
    if customer_id and not customer_id.startswith("C"):
        raise PermissionDeniedError(
            "OP_CUSTOMER_OUT_OF_SCOPE",
            "customer is outside the operator's accessible scope",
        )

