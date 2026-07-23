import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.operation.mock_routes import router as mock_router
from app.api.operation.routes import router as operation_router
from app.config.settings import get_settings
from app.container import build_container
from app.event.channels import EventChannel
from app.utils.exceptions import ConflictError, NotFoundError, OperatorError


async def monitor_risk_timeouts(app: FastAPI) -> None:
    while True:
        await app.state.container.operation_service.expire_risk_reviews()
        await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    container = await build_container(get_settings())
    app.state.container = container
    subscriber_task: asyncio.Task | None = None
    timeout_task = asyncio.create_task(monitor_risk_timeouts(app))
    if container.subscriber:
        subscriber_task = asyncio.create_task(
            container.subscriber.listen(
                [
                    EventChannel.OPERATOR_COMMAND,
                    EventChannel.OPERATOR_RISK_RESULT,
                    EventChannel.OPERATOR_CONTROL,
                ],
                container.event_router.handle,
            )
        )
    try:
        yield
    finally:
        await container.close()
        if subscriber_task:
            subscriber_task.cancel()
            with suppress(asyncio.CancelledError):
                await subscriber_task
        timeout_task.cancel()
        with suppress(asyncio.CancelledError):
            await timeout_task


app = FastAPI(
    title="WealthSense Business Operator",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(operation_router)
app.include_router(mock_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.exception_handler(OperatorError)
async def operator_error_handler(
    request: Request,
    exc: OperatorError,
) -> JSONResponse:
    del request
    status_code = 400
    if isinstance(exc, NotFoundError):
        status_code = 404
    elif isinstance(exc, ConflictError):
        status_code = 409
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "retryable": exc.retryable,
                "details": exc.details,
            }
        },
    )
