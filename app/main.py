"""WealthSense FastAPI 应用入口。"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.api.chat import router as chat_router
from app.api.knowledge import router as knowledge_router
from app.api.system import router as system_router
from app.config import get_settings
from app.dao import get_database_manager
from app.utils.exception_handlers import register_exception_handlers
from app.utils.logger import TraceIdMiddleware, configure_logging


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await get_database_manager().close_all()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(level=settings.log_level, json_output=settings.log_json)
    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        docs_url="/api/docs",
        lifespan=lifespan,
    )
    app.add_middleware(TraceIdMiddleware)
    register_exception_handlers(app)
    app.include_router(system_router)
    app.include_router(knowledge_router)
    app.include_router(chat_router)

    @app.get("/docs", include_in_schema=False)
    async def docs_redirect():
        return RedirectResponse("/api/docs")

    return app


app = create_app()
