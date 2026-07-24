"""风控访问策略：谁可调、可返哪些字段。"""

from __future__ import annotations

from typing import Any

from app.models.entities.risk_alert import RiskAlertRecord
from app.models.schemas.auth import CurrentUser, Permission, UserRole
from app.utils.exceptions import PermissionDeniedError

SENSITIVE_EXTRA_KEYS = frozenset(
    {
        "id_card",
        "身份证",
        "身份证号",
        "bank_card",
        "card_no",
        "银行卡",
        "phone",
        "mobile",
        "手机号",
        "holdings",
        "持仓",
        "资产",
    }
)

ALLOWED_HANDLE_STATUSES = frozenset({"未处理", "已确认", "已排除"})


def assert_can_monitor(user: CurrentUser) -> None:
    if not user.has_permission(Permission.RISK_READ) and not user.has_role(
        UserRole.RISK_OFFICER, UserRole.ADMIN
    ):
        raise PermissionDeniedError(message="无权调用风控监测接口")


def assert_can_read_alerts(user: CurrentUser) -> None:
    if not user.has_permission(Permission.RISK_READ):
        raise PermissionDeniedError(message="无权查询风控预警")


def assert_can_handle(user: CurrentUser) -> None:
    if not user.has_permission(Permission.RISK_HANDLE):
        raise PermissionDeniedError(message="无权处置风控预警")


def scrub_extra(extra: dict[str, Any] | None) -> dict[str, Any]:
    if not extra:
        return {}
    return {
        key: value
        for key, value in extra.items()
        if key not in SENSITIVE_EXTRA_KEYS
        and not any(s in str(key) for s in ("身份证", "银行卡", "持仓"))
    }


def alert_to_public_dict(record: RiskAlertRecord) -> dict[str, Any]:
    """仅返回允许字段：评判结果、级别、规则、原因、置信度、复核与状态。"""

    return {
        "alert_id": record.id,
        "customer_id": record.customer_id,
        "record_type": record.record_type,
        "alert_level": record.alert_level,
        "hit_rules": record.hit_rules,
        "reason": record.reason,
        "confidence": record.confidence,
        "llm_review": record.llm_review,
        "llm_conflict": record.llm_conflict,
        "status": record.status,
        "work_order_id": record.work_order_id,
        "broadcasted": record.broadcasted,
        "created_at": record.created_at.isoformat(),
    }
