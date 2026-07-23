"""Public application exceptions and operator-specific domain errors."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from app.models.error_codes import ErrorCode, get_error_definition


class AppException(Exception):
    """Base exception exposed through the shared API response envelope."""

    def __init__(
        self,
        code: ErrorCode,
        *,
        message: str | None = None,
        details: Any | None = None,
        http_status: HTTPStatus | int | None = None,
    ) -> None:
        definition = get_error_definition(code)
        self.code = code
        self.message = message or definition.message
        self.details = details
        self.http_status = int(http_status or definition.http_status)
        super().__init__(self.message)


class ConfigurationError(AppException):
    def __init__(self, message: str = "应用配置无效") -> None:
        super().__init__(ErrorCode.CONFIGURATION_ERROR, message=message)


class DatabaseConnectionError(AppException):
    def __init__(self, database: str) -> None:
        super().__init__(
            ErrorCode.DATABASE_CONNECTION_ERROR,
            message=f"{database} 数据库连接失败",
            details={"database": database},
        )


class AuthenticationError(AppException):
    def __init__(
        self,
        *,
        code: ErrorCode = ErrorCode.UNAUTHORIZED,
        message: str | None = None,
    ) -> None:
        super().__init__(code, message=message)


class PermissionDeniedError(AppException):
    def __init__(self, message: str = "无权执行该操作") -> None:
        super().__init__(ErrorCode.FORBIDDEN, message=message)


class ResourceNotFoundError(AppException):
    def __init__(self, resource: str = "资源") -> None:
        super().__init__(
            ErrorCode.NOT_FOUND,
            message=f"{resource}不存在",
            details={"resource": resource},
        )


class ConflictError(AppException):
    def __init__(self, message: str = "资源状态冲突") -> None:
        super().__init__(ErrorCode.CONFLICT, message=message)


class OperatorError(Exception):
    """Error returned by the Business Operator Agent API."""

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


class OperatorNotFoundError(OperatorError):
    pass


class OperatorConflictError(OperatorError):
    pass


class OperatorPermissionDeniedError(OperatorError):
    pass
