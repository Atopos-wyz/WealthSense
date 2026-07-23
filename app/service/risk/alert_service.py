"""预警读写服务。"""

from __future__ import annotations

from app.dao.mysql.risk_alert_dao import InMemoryRiskAlertStore, RiskAlertStore
from app.models.entities.risk_alert import RiskAlertRecord
from app.service.risk.access_policy import alert_to_public_dict
from app.utils.exceptions import AppException
from app.models.error_codes import ErrorCode


class RiskAlertService:
    def __init__(self, store: RiskAlertStore | None = None) -> None:
        self._store = store or InMemoryRiskAlertStore()

    @property
    def store(self) -> RiskAlertStore:
        return self._store

    async def save(self, record: RiskAlertRecord) -> RiskAlertRecord:
        return await self._store.create(record)

    async def get_public(self, alert_id: int) -> dict:
        record = await self._store.get(alert_id)
        if record is None:
            raise AppException(code=ErrorCode.NOT_FOUND, message="预警不存在")
        return alert_to_public_dict(record)

    async def list_public(self, customer_id: str) -> list[dict]:
        records = await self._store.list_by_customer(customer_id)
        return [alert_to_public_dict(item) for item in records]

    async def mark_broadcasted(self, alert_id: int) -> None:
        await self._store.mark_broadcasted(alert_id)
