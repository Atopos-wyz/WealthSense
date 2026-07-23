"""统一 API 响应结构的工厂函数。"""

from __future__ import annotations

from typing import Any, TypeVar

from app.models.error_codes import ErrorCode, get_error_definition
from app.models.schemas.response import ApiResponse
from app.utils.logger import get_trace_id

T = TypeVar("T")


def success_response(
    data: T | None = None,
    *,
    message: str = "success",
    trace_id: str | None = None,
) -> ApiResponse[T]:
    return ApiResponse[T](
        code=ErrorCode.SUCCESS,
        message=message,
        data=data,
        trace_id=trace_id or get_trace_id(),
    )


def failure_response(
    code: ErrorCode,
    *,
    message: str | None = None,
    details: Any | None = None,
    trace_id: str | None = None,
) -> ApiResponse[Any]:
    definition = get_error_definition(code)
    data = {"details": details} if details is not None else None
    return ApiResponse[Any](
        code=definition.code,
        message=message or definition.message,
        data=data,
        trace_id=trace_id or get_trace_id(),
    )
