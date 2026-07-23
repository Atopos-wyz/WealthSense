import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.operation.mock_routes import router as mock_router
from app.api.operation.routes import router as operation_router
from app.api.risk.monitor_router import router as risk_monitor_router
from app.api.risk.pages import pages_router
from app.config.settings import get_settings
from app.container import AppContainer, build_container
from app.event.channels import EventChannel
from app.utils.exception_handlers import register_exception_handlers
from app.utils.exceptions import (
    OperatorConflictError as ConflictError,
    OperatorError,
    OperatorNotFoundError as NotFoundError,
    OperatorPermissionDeniedError as PermissionDeniedError,
)
from app.utils.logger import TraceIdMiddleware

logger = logging.getLogger(__name__)


async def monitor_risk_timeouts(
    app: FastAPI,
    stop_event: asyncio.Event,
) -> None:
    while not stop_event.is_set():
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
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=1)
        except TimeoutError:
            pass


async def finish_background_task(
    task: asyncio.Task,
    *,
    name: str,
    timeout: float,
) -> None:
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
    except TimeoutError:
        task.cancel()
        try:
            await asyncio.wait_for(
                asyncio.shield(task),
                timeout=timeout,
            )
        except TimeoutError:
            logger.error("%s ignored cancellation", name)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("%s failed while being cancelled", name)
        logger.warning("%s did not stop before timeout", name)
    except asyncio.CancelledError:
        if not task.cancelled():
            raise
    except Exception:
        logger.exception("%s stopped with an error", name)


async def _shutdown_application(
    container: AppContainer,
    subscriber_task: asyncio.Task | None,
    timeout_task: asyncio.Task,
    stop_event: asyncio.Event,
) -> None:
    try:
        if subscriber_task:
            container.subscriber.stop()
            await finish_background_task(
                subscriber_task,
                name="Redis event subscriber",
                timeout=2,
            )
        stop_event.set()
        await finish_background_task(
            timeout_task,
            name="operator maintenance task",
            timeout=10,
        )
    finally:
        await container.close()


async def _wait_for_shutdown(task: asyncio.Task) -> bool:
    was_cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            was_cancelled = True
    return was_cancelled


@asynccontextmanager
async def lifespan(app: FastAPI):
    container = await build_container(get_settings())
    app.state.container = container
    subscriber_task: asyncio.Task | None = None
    stop_event = asyncio.Event()
    timeout_task = asyncio.create_task(
        monitor_risk_timeouts(app, stop_event)
    )
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
        shutdown_task = asyncio.create_task(
            _shutdown_application(
                container,
                subscriber_task,
                timeout_task,
                stop_event,
            )
        )
        cancelled_during_shutdown = await _wait_for_shutdown(shutdown_task)
        if shutdown_task.cancelled():
            raise asyncio.CancelledError
        shutdown_task.result()
        if cancelled_during_shutdown:
            raise asyncio.CancelledError


app = FastAPI(
    title="WealthSense Business Operator",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(TraceIdMiddleware)
register_exception_handlers(app)
app.include_router(operation_router)
app.include_router(risk_monitor_router)
app.include_router(pages_router)
try:
    from app.api.risk.router import router as risk_assessment_router

    app.include_router(risk_assessment_router)
except Exception:
    logger.exception("风险评估路由未挂载（依赖未就绪）")
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
