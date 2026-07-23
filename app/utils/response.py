"""统一响应构造。"""

from typing import TypeVar

from fastapi import Request

from app.models.schemas.common import ApiResponse


T = TypeVar("T")


def success(request: Request, data: T, message: str = "success") -> ApiResponse[T]:
    return ApiResponse[T](
        code=200,
        message=message,
        data=data,
        trace_id=request.state.trace_id,
    )
