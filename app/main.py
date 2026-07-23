import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.operation.mock_routes import router as mock_router
from app.api.operation.routes import router as operation_router
from app.config.settings import get_settings
from app.container import build_container
from app.event.channels import EventChannel
from app.utils.exceptions import (
    ConflictError,
    NotFoundError,
    OperatorError,
    PermissionDeniedError,
)

logger = logging.getLogger(__name__)


async def monitor_risk_timeouts(app: FastAPI) -> None:
    while True:
        service = app.state.container.operation_service
        maintenance_steps = (
            service.expire_risk_reviews,
            service.expire_confirmations,
            service.resume_ready_operations,
            service.reconcile_pending_operations,
        )
        for step in maintenance_steps:
            try:
                await step()
            except Exception:
                logger.exception(
                    "operator maintenance step failed: %s",
                    step.__name__,
                )
        publisher = app.state.container.publisher
        if hasattr(publisher, "flush_pending"):
            try:
                await publisher.flush_pending()
            except Exception:
                logger.exception("operator outbox flush failed")
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
        if subscriber_task:
            subscriber_task.cancel()
            with suppress(asyncio.CancelledError):
                await subscriber_task
        timeout_task.cancel()
        with suppress(asyncio.CancelledError):
            await timeout_task
        await container.close()


app = FastAPI(
    title="WealthSense Business Operator",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(operation_router)
if not get_settings().is_production:
    app.include_router(mock_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
async def readiness(request: Request) -> JSONResponse:
    container = request.app.state.container
    if not container.engine or not container.redis:
        return JSONResponse(
            status_code=200,
            content={"status": "ready", "mode": "in_memory"},
        )
    try:
        async with container.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        await container.redis.ping()
    except Exception:
        logger.exception("readiness dependency check failed")
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready"},
        )
    return JSONResponse(
        status_code=200,
        content={"status": "ready", "mode": "mysql_redis"},
    )


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
    elif isinstance(exc, PermissionDeniedError):
        status_code = 403
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
