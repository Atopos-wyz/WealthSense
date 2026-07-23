from app.models.schemas.common import OperationStatus


ALLOWED_TRANSITIONS: dict[OperationStatus, set[OperationStatus]] = {
    OperationStatus.DRAFT: {
        OperationStatus.RESOLVING_ENTITIES,
        OperationStatus.CANCELLED,
    },
    OperationStatus.RESOLVING_ENTITIES: {
        OperationStatus.VALIDATING,
        OperationStatus.NEED_MORE_INFORMATION,
        OperationStatus.VALIDATION_FAILED,
    },
    OperationStatus.NEED_MORE_INFORMATION: {
        OperationStatus.RESOLVING_ENTITIES,
        OperationStatus.CANCELLED,
        OperationStatus.EXPIRED,
    },
    OperationStatus.VALIDATING: {
        OperationStatus.PERMISSION_DENIED,
        OperationStatus.VALIDATION_FAILED,
        OperationStatus.WAITING_RISK_REVIEW,
    },
    OperationStatus.WAITING_RISK_REVIEW: {
        OperationStatus.RESOLVING_ENTITIES,
        OperationStatus.RISK_APPROVED,
        OperationStatus.RISK_REJECTED,
        OperationStatus.RISK_REVIEW_TIMEOUT,
        OperationStatus.MANUAL_REVIEW,
        OperationStatus.CANCELLED,
    },
    OperationStatus.RISK_APPROVED: {
        OperationStatus.RESOLVING_ENTITIES,
        OperationStatus.PENDING_CONFIRMATION,
        OperationStatus.EXECUTING,
        OperationStatus.CANCELLED,
    },
    OperationStatus.PENDING_CONFIRMATION: {
        OperationStatus.RESOLVING_ENTITIES,
        OperationStatus.CONFIRMED,
        OperationStatus.CANCELLED,
        OperationStatus.EXPIRED,
    },
    OperationStatus.CONFIRMED: {
        OperationStatus.EXECUTING,
        OperationStatus.CANCELLED,
    },
    OperationStatus.EXECUTING: {
        OperationStatus.SUCCEEDED,
        OperationStatus.FAILED,
        OperationStatus.PENDING_VERIFICATION,
    },
    OperationStatus.PENDING_VERIFICATION: {
        OperationStatus.SUCCEEDED,
        OperationStatus.FAILED,
        OperationStatus.MANUAL_REVIEW,
    },
    OperationStatus.MANUAL_REVIEW: {
        OperationStatus.RISK_APPROVED,
        OperationStatus.RISK_REJECTED,
        OperationStatus.CANCELLED,
    },
}

TERMINAL_STATUSES = {
    OperationStatus.PERMISSION_DENIED,
    OperationStatus.VALIDATION_FAILED,
    OperationStatus.RISK_REJECTED,
    OperationStatus.RISK_REVIEW_TIMEOUT,
    OperationStatus.SUCCEEDED,
    OperationStatus.FAILED,
    OperationStatus.CANCELLED,
    OperationStatus.EXPIRED,
}


class InvalidStateTransition(ValueError):
    pass


def assert_transition(
    current_status: OperationStatus,
    target_status: OperationStatus,
) -> None:
    allowed = ALLOWED_TRANSITIONS.get(current_status, set())
    if target_status not in allowed:
        raise InvalidStateTransition(
            f"cannot transition from {current_status} to {target_status}"
        )
