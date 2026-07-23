"""风控预警仓储（默认内存；可选 MySQL）。"""

from __future__ import annotations

import json
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities.risk_alert import RiskAlertEntity, RiskAlertRecord, utc_now


class RiskAlertStore(Protocol):
    async def create(self, record: RiskAlertRecord) -> RiskAlertRecord: ...

    async def get(self, alert_id: int) -> RiskAlertRecord | None: ...

    async def list_by_customer(self, customer_id: str) -> list[RiskAlertRecord]: ...

    async def update_status(
        self, alert_id: int, status: str
    ) -> RiskAlertRecord | None: ...

    async def mark_broadcasted(self, alert_id: int) -> None: ...


class InMemoryRiskAlertStore:
    """进程内仓储，便于本地/单测，不依赖 MySQL。"""

    def __init__(self) -> None:
        self._items: dict[int, RiskAlertRecord] = {}
        self._seq = 0

    async def create(self, record: RiskAlertRecord) -> RiskAlertRecord:
        self._seq += 1
        record.id = self._seq
        if record.alert_level in {"中", "高"} and record.record_type == "alert":
            record.work_order_id = record.work_order_id or f"WO-{record.id}"
        self._items[record.id] = record
        return record

    async def get(self, alert_id: int) -> RiskAlertRecord | None:
        return self._items.get(alert_id)

    async def list_by_customer(self, customer_id: str) -> list[RiskAlertRecord]:
        return [
            item
            for item in self._items.values()
            if item.customer_id == customer_id
        ]

    async def update_status(
        self, alert_id: int, status: str
    ) -> RiskAlertRecord | None:
        item = self._items.get(alert_id)
        if item is None:
            return None
        item.status = status
        return item

    async def mark_broadcasted(self, alert_id: int) -> None:
        item = self._items.get(alert_id)
        if item is not None:
            item.broadcasted = True


class MySQLRiskAlertStore:
    """MySQL 实现；由调用方注入已打开的 AsyncSession。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, record: RiskAlertRecord) -> RiskAlertRecord:
        entity = RiskAlertEntity(
            customer_id=record.customer_id,
            record_type=record.record_type,
            alert_level=record.alert_level,
            hit_rules_json=json.dumps(record.hit_rules, ensure_ascii=False),
            reason=record.reason,
            confidence=record.confidence,
            llm_review=record.llm_review,
            status=record.status,
            work_order_id=record.work_order_id,
            broadcasted=record.broadcasted,
            created_at=record.created_at or utc_now(),
        )
        self._session.add(entity)
        await self._session.flush()
        if entity.alert_level in {"中", "高"} and entity.record_type == "alert":
            entity.work_order_id = entity.work_order_id or f"WO-{entity.id}"
        await self._session.commit()
        await self._session.refresh(entity)
        return _entity_to_record(entity)

    async def get(self, alert_id: int) -> RiskAlertRecord | None:
        entity = await self._session.get(RiskAlertEntity, alert_id)
        return _entity_to_record(entity) if entity else None

    async def list_by_customer(self, customer_id: str) -> list[RiskAlertRecord]:
        result = await self._session.execute(
            select(RiskAlertEntity).where(RiskAlertEntity.customer_id == customer_id)
        )
        return [_entity_to_record(item) for item in result.scalars().all()]

    async def update_status(
        self, alert_id: int, status: str
    ) -> RiskAlertRecord | None:
        entity = await self._session.get(RiskAlertEntity, alert_id)
        if entity is None:
            return None
        entity.status = status
        await self._session.commit()
        await self._session.refresh(entity)
        return _entity_to_record(entity)

    async def mark_broadcasted(self, alert_id: int) -> None:
        entity = await self._session.get(RiskAlertEntity, alert_id)
        if entity is None:
            return
        entity.broadcasted = True
        await self._session.commit()


def _entity_to_record(entity: RiskAlertEntity) -> RiskAlertRecord:
    try:
        hit_rules = json.loads(entity.hit_rules_json or "[]")
    except json.JSONDecodeError:
        hit_rules = []
    return RiskAlertRecord(
        id=entity.id,
        customer_id=entity.customer_id,
        record_type=entity.record_type,
        alert_level=entity.alert_level,
        hit_rules=hit_rules if isinstance(hit_rules, list) else [],
        reason=entity.reason,
        confidence=entity.confidence,
        llm_review=entity.llm_review,
        status=entity.status,
        work_order_id=entity.work_order_id,
        broadcasted=entity.broadcasted,
        created_at=entity.created_at,
    )
