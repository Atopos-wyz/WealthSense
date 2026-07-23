"""WealthSense FastAPI 应用入口。"""

from uuid import uuid4

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.profile.router import router as profile_router
from app.api.risk.router import router as risk_router
from app.config.settings import get_settings
from app.models.schemas.common import ApiResponse
from app.utils.exceptions import BusinessError


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="客户画像、四维研判、风险问卷与适当性检查接口",
)


@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    request.state.trace_id = request.headers.get(
        "X-Trace-ID",
        str(uuid4()),
    )
    response = await call_next(request)
    response.headers["X-Trace-ID"] = request.state.trace_id
    return response


@app.exception_handler(BusinessError)
async def business_error_handler(
    request: Request,
    exc: BusinessError,
) -> JSONResponse:
    payload = ApiResponse[None](
        code=exc.code,
        message=exc.message,
        data=None,
        trace_id=request.state.trace_id,
    )
    return JSONResponse(
        status_code=exc.http_status,
        content=payload.model_dump(mode="json"),
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    payload = ApiResponse[list[dict]](
        code=400,
        message="请求参数校验失败",
        data=exc.errors(),
        trace_id=request.state.trace_id,
    )
    return JSONResponse(
        status_code=422,
        content=payload.model_dump(mode="json"),
    )


@app.get("/health", tags=["系统"])
async def health(request: Request) -> ApiResponse[dict[str, str]]:
    return ApiResponse[dict[str, str]](
        data={"status": "UP"},
        trace_id=request.state.trace_id,
    )


app.include_router(profile_router)
app.include_router(risk_router)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)