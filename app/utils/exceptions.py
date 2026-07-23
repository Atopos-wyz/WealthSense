from typing import Any


class OperatorError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}


class NotFoundError(OperatorError):
    pass


class ConflictError(OperatorError):
    pass


class PermissionDeniedError(OperatorError):
    pass

