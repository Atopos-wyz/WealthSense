"""WealthSense FastAPI 入口。

当前仅挂载风控监测路由与联调台页面；其他模块可在此按需 include_router。
"""

from __future__ import annotations

from fastapi import FastAPI

from app.api.risk import router as risk_router
from app.api.risk.pages import pages_router
from app.utils.exception_handlers import register_exception_handlers
from app.utils.logger import TraceIdMiddleware

app = FastAPI(title="WealthSense", version="0.1.0")
app.add_middleware(TraceIdMiddleware)
register_exception_handlers(app)
app.include_router(risk_router)
app.include_router(pages_router)
