"""WealthSense FastAPI 应用入口。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.api.chat.advisor import router as advisor_router
from app.api.profile.router import router as profile_router
from app.api.risk.router import router as risk_router
from app.config.settings import get_settings
from app.dao import get_database_manager
from app.models.schemas import ApiResponse
from app.utils.exception_handlers import register_exception_handlers
from app.utils.logger import (
    TraceIdMiddleware,
    configure_logging,
)
from app.view.response import success_response


settings = get_settings()
configure_logging(
    level=settings.log_level,
    json_output=settings.log_json,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """连接按请求懒加载，应用关闭时统一释放。"""

    yield
    await get_database_manager().close_all()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="客户画像、四维研判、风险问卷与适当性检查接口",
    lifespan=lifespan,
)
app.add_middleware(TraceIdMiddleware)
register_exception_handlers(app)


@app.get("/health", tags=["系统"])
async def health() -> ApiResponse[dict[str, str]]:
    return success_response({"status": "UP"})


app.include_router(profile_router)
app.include_router(risk_router)
app.include_router(advisor_router)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
