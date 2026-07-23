from datetime import timedelta
from decimal import Decimal

from app.models.schemas.common import OperationIntent, utc_now
from app.models.schemas.internal import OperationRecord
from app.models.schemas.operation import ConfirmOperationRequest
from app.utils.exceptions import OperatorConflictError as ConflictError


def requires_confirmation(
    intent: OperationIntent,
    params: dict,
) -> bool:
    if intent == OperationIntent.PURCHASE:
        return Decimal(str(params["amount"])) > Decimal("10000")
    if intent == OperationIntent.TRANSFER:
        return Decimal(str(params["amount"])) > Decimal("50000")
    return intent in {
        OperationIntent.REDEEM,
        OperationIntent.RISK_REASSESSMENT,
        OperationIntent.UPDATE_PROFILE,
    }


def validate_confirmation(
    operation: OperationRecord,
    request: ConfirmOperationRequest,
) -> None:
    if request.operation_version != operation.version:
        raise ConflictError(
            "OP_CONFIRMATION_VERSION_MISMATCH",
            "操作参数版本已变化，请重新确认",
        )
    if request.params_hash != operation.params_hash:
        raise ConflictError(
            "OP_CONFIRMATION_VERSION_MISMATCH",
            "操作参数已变化，请重新确认",
        )


def confirmation_values(
    operation: OperationRecord,
    request: ConfirmOperationRequest,
    ttl_seconds: int,
) -> dict:
    now = utc_now()
    return {
        "operation_id": operation.operation_id,
        "operation_version": operation.version,
        "params_hash": operation.params_hash,
        "confirmed_by": request.confirmer_id,
        "confirmation_method": request.confirmation_method,
        "status": "confirmed",
        "confirmed_at": now,
        "expires_at": now + timedelta(seconds=ttl_seconds),
    }
