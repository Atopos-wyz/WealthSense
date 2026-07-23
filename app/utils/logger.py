"""结构化日志与请求链路上下文。"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

TRACE_HEADER = "X-Trace-ID"
_trace_id_context: ContextVar[str | None] = ContextVar(
    "wealthsense_trace_id", default=None
)


def get_trace_id() -> str:
    trace_id = _trace_id_context.get()
    if trace_id is None:
        trace_id = str(uuid4())
        _trace_id_context.set(trace_id)
    return trace_id


def set_trace_id(trace_id: str | None = None) -> Token[str | None]:
    return _trace_id_context.set(trace_id or str(uuid4()))


def reset_trace_id(token: Token[str | None]) -> None:
    _trace_id_context.reset(token)


class JsonFormatter(logging.Formatter):
    """每行输出一个 JSON 对象，并避免泄露任意对象内容。"""

    _optional_fields = (
        "event",
        "user_id",
        "agent_type",
        "tool_name",
        "database",
        "duration_ms",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": getattr(record, "trace_id", None) or get_trace_id(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        for field in self._optional_fields:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(
    *,
    level: str = "INFO",
    json_output: bool = True,
) -> None:
    """按指定格式一次性配置进程级日志。"""

    root = logging.getLogger()
    root.setLevel(level.upper())

    handler = logging.StreamHandler(sys.stdout)
    if json_output:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s "
                "[trace_id=%(trace_id)s] %(message)s"
            )
        )
    handler.addFilter(TraceIdFilter())

    root.handlers.clear()
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


class TraceIdFilter(logging.Filter):
    """为标准文本日志记录附加当前链路标识。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = getattr(record, "trace_id", None) or get_trace_id()
        return True


class TraceIdMiddleware(BaseHTTPMiddleware):
    """为每个 HTTP 请求传递或创建链路标识。"""

    async def dispatch(self, request: Request, call_next):
        incoming_trace_id = request.headers.get(TRACE_HEADER)
        token = set_trace_id(incoming_trace_id)
        try:
            response = await call_next(request)
            response.headers[TRACE_HEADER] = get_trace_id()
            return response
        finally:
            reset_trace_id(token)
