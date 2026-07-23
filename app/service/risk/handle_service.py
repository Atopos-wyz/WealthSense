"""专员处置预警状态。"""

from __future__ import annotations

from app.dao.mysql.risk_alert_dao import RiskAlertStore
from app.models.error_codes import ErrorCode
from app.service.risk.access_policy import ALLOWED_HANDLE_STATUSES, alert_to_public_dict
from app.utils.exceptions import AppException


class RiskHandleService:
    def __init__(self, store: RiskAlertStore) -> None:
        self._store = store

    async def handle(self, alert_id: int, status: str) -> dict:
        if status not in ALLOWED_HANDLE_STATUSES:
            raise AppException(
                code=ErrorCode.INVALID_ARGUMENT,
                message=f"非法处置状态，允许：{sorted(ALLOWED_HANDLE_STATUSES)}",
            )
        record = await self._store.update_status(alert_id, status)
        if record is None:
            raise AppException(code=ErrorCode.NOT_FOUND, message="预警不存在")
        return alert_to_public_dict(record)
