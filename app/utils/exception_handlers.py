"""适配统一响应约定的 FastAPI 异常处理器。"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.models.error_codes import ErrorCode, get_error_definition
from app.models.schemas.response import ErrorItem
from app.utils.exceptions import AppException
from app.utils.logger import get_logger, get_trace_id
from app.view.response import failure_response

logger = get_logger(__name__)


def _json_response(
    *,
    status_code: int,
    code: ErrorCode,
    message: str | None = None,
    details: Any | None = None,
) -> JSONResponse:
    body = failure_response(
        code,
        message=message,
        details=details,
        trace_id=get_trace_id(),
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json"),
    )


async def app_exception_handler(
    _: Request,
    exc: AppException,
) -> JSONResponse:
    return _json_response(
        status_code=exc.http_status,
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


async def validation_exception_handler(
    _: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    errors = [
        ErrorItem(
            location=list(error.get("loc", ())),
            message=error.get("msg", "参数值无效"),
            error_type=error.get("type"),
        ).model_dump(mode="json")
        for error in exc.errors()
    ]
    definition = get_error_definition(ErrorCode.INVALID_ARGUMENT)
    return _json_response(
        status_code=definition.http_status,
        code=definition.code,
        details=errors,
    )


async def http_exception_handler(
    _: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    code_by_status = {
        400: ErrorCode.INVALID_ARGUMENT,
        401: ErrorCode.UNAUTHORIZED,
        403: ErrorCode.FORBIDDEN,
        404: ErrorCode.NOT_FOUND,
        409: ErrorCode.CONFLICT,
    }
    code = code_by_status.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
    return _json_response(
        status_code=exc.status_code,
        code=code,
        message=str(exc.detail) if exc.detail else None,
    )


async def unhandled_exception_handler(
    _: Request,
    exc: Exception,
) -> JSONResponse:
    logger.error(
        "未处理的应用异常",
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    definition = get_error_definition(ErrorCode.INTERNAL_ERROR)
    return _json_response(
        status_code=definition.http_status,
        code=definition.code,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """在 FastAPI 应用中注册全部公共异常映射。"""

    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
