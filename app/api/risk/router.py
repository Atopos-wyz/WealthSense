"""风控监测 API（仅本模块路由）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.config.settings import Settings, get_settings
from app.dao.mysql.risk_alert_dao import InMemoryRiskAlertStore
from app.dao.redis.connection import RedisConnectionManager
from app.event.publisher import (
    CompositeEventPublisher,
    InMemoryEventPublisher,
    RedisEventPublisher,
)
from app.models.schemas.auth import CurrentUser, Permission, UserRole
from app.models.schemas.response import ApiResponse
from app.models.schemas.risk import (
    AlertView,
    HandleAlertRequest,
    MonitorRequest,
    MonitorResponse,
)
from app.service.risk.access_policy import assert_can_handle, assert_can_read_alerts
from app.service.risk.alert_service import RiskAlertService
from app.service.risk.handle_service import RiskHandleService
from app.service.risk.monitor_service import RiskMonitorService
from app.service.risk.reason_llm import ReasonLlmService
from app.utils.logger import get_logger
from app.utils.permissions import create_access_token, require_permissions
from app.view.response import success_response

logger = get_logger(__name__)

router = APIRouter(prefix="/api/risk", tags=["risk"])

_memory_publisher = InMemoryEventPublisher()
_alert_store = InMemoryRiskAlertStore()


def _build_publisher() -> CompositeEventPublisher:
    """内存必发；Redis 按配置尝试挂上（失败不影响主链路）。"""

    redis_publisher: RedisEventPublisher | None = None
    try:
        settings = get_settings()
        redis_mgr = RedisConnectionManager(settings)
        redis_publisher = RedisEventPublisher(redis_mgr)
        logger.info("风控广播已挂载 Redis 发布器 channel=event:risk_alert")
    except Exception:
        logger.warning("风控广播未挂载 Redis，仅使用内存总线", exc_info=True)
    return CompositeEventPublisher(
        memory=_memory_publisher,
        redis_publisher=redis_publisher,
    )


_monitor_service = RiskMonitorService(
    store=_alert_store,
    publisher=_build_publisher(),
    memory_publisher=_memory_publisher,
    llm=ReasonLlmService(mode="mock"),
)
_alert_service = RiskAlertService(_alert_store)
_handle_service = RiskHandleService(_alert_store)
_event_publisher = _monitor_service.publisher


@router.post(
    "/monitor",
    response_model=ApiResponse[MonitorResponse],
    summary="交易行为反洗钱监测",
)
async def monitor_transaction(
    body: MonitorRequest,
    _: CurrentUser = Depends(require_permissions(Permission.RISK_READ)),
) -> ApiResponse[MonitorResponse]:
    result = await _monitor_service.monitor(body)
    return success_response(result)


@router.get(
    "/alerts",
    response_model=ApiResponse[list[AlertView]],
    summary="按客户查询预警（字段白名单）",
)
async def list_alerts(
    customer_id: str = Query(min_length=1),
    user: CurrentUser = Depends(require_permissions(Permission.RISK_READ)),
) -> ApiResponse[list[AlertView]]:
    assert_can_read_alerts(user)
    items = await _alert_service.list_public(customer_id)
    return success_response([AlertView.model_validate(item) for item in items])


@router.get(
    "/alerts/{alert_id}",
    response_model=ApiResponse[AlertView],
    summary="查询单条预警详情",
)
async def get_alert(
    alert_id: int,
    user: CurrentUser = Depends(require_permissions(Permission.RISK_READ)),
) -> ApiResponse[AlertView]:
    assert_can_read_alerts(user)
    item = await _alert_service.get_public(alert_id)
    return success_response(AlertView.model_validate(item))


@router.post(
    "/alerts/{alert_id}/handle",
    response_model=ApiResponse[AlertView],
    summary="专员处置预警状态",
)
async def handle_alert(
    alert_id: int,
    body: HandleAlertRequest,
    user: CurrentUser = Depends(require_permissions(Permission.RISK_HANDLE)),
) -> ApiResponse[AlertView]:
    assert_can_handle(user)
    item = await _handle_service.handle(alert_id, body.status)
    return success_response(AlertView.model_validate(item))


@router.get(
    "/dev/last-events",
    response_model=ApiResponse[list[dict]],
    summary="[开发] 查看内存中已广播事件（自证用）",
)
async def last_events(
    _: CurrentUser = Depends(require_permissions(Permission.RISK_READ)),
    settings: Settings = Depends(get_settings),
) -> ApiResponse[list[dict]]:
    if settings.app_env == "production":
        return success_response([])
    return success_response(
        [{"channel": ch, "payload": payload} for ch, payload in _memory_publisher.published]
    )


@router.get(
    "/dev/redis-status",
    response_model=ApiResponse[dict],
    summary="[开发] 检查 Redis 连通与最近广播状态",
)
async def redis_status(
    _: CurrentUser = Depends(require_permissions(Permission.RISK_READ)),
    settings: Settings = Depends(get_settings),
) -> ApiResponse[dict]:
    from app.event.channels import RISK_ALERT_CHANNEL

    enabled = isinstance(_event_publisher, CompositeEventPublisher) and (
        _event_publisher.redis_enabled
    )
    ping_ok = False
    ping_error: str | None = None
    if enabled:
        try:
            redis_mgr = RedisConnectionManager(settings)
            await redis_mgr.connect()
            ping_ok = bool(await redis_mgr.client.ping())
            await redis_mgr.close()
        except Exception as exc:
            ping_error = str(exc)

    last_ok = getattr(_event_publisher, "last_redis_ok", False)
    last_err = getattr(_event_publisher, "last_redis_error", None)
    return success_response(
        {
            "channel": RISK_ALERT_CHANNEL,
            "redis_host": settings.redis_host,
            "redis_port": settings.redis_port,
            "redis_db": settings.redis_db,
            "publisher_redis_enabled": enabled,
            "ping_ok": ping_ok,
            "ping_error": ping_error,
            "last_redis_ok": last_ok,
            "last_redis_error": last_err,
            "hint": (
                "先 SUBSCRIBE event:risk_alert，再在联调台提交中/高命中；"
                "看 redis_published / receivers。"
            ),
        }
    )


@router.post(
    "/dev/token",
    response_model=ApiResponse[dict],
    summary="[开发] 签发风控专员测试 JWT",
)
async def issue_dev_token(
    settings: Settings = Depends(get_settings),
) -> ApiResponse[dict]:
    if settings.app_env == "production":
        return success_response({"token": None, "message": "生产环境禁用"})
    token = create_access_token(
        subject="risk-dev",
        roles=[UserRole.RISK_OFFICER],
        settings=settings,
    )
    return success_response(
        {
            "token": token,
            "token_type": "Bearer",
            "usage": "Authorization: Bearer <token>",
        }
    )
