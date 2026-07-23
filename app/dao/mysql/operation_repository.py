from copy import deepcopy
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.entities import (
    AuditLogEntity,
    ConfirmationEntity,
    ExecutionAttemptEntity,
    OperationEntity,
    OperationVersionEntity,
    ProcessedEventEntity,
    RiskReviewEntity,
)
from app.models.schemas.common import AgentId, OperationIntent, OperationStatus, utc_now
from app.models.schemas.internal import OperationRecord


class OperationRepository(Protocol):
    async def create(self, record: OperationRecord) -> None: ...
    async def get(self, operation_id: str) -> OperationRecord | None: ...
    async def save(self, record: OperationRecord) -> None: ...
    async def add_version(self, record: OperationRecord, changed_by: str) -> None: ...
    async def add_risk_review(self, values: dict[str, Any]) -> None: ...
    async def update_risk_review(
        self, request_event_id: str, values: dict[str, Any]
    ) -> None: ...
    async def add_confirmation(self, values: dict[str, Any]) -> None: ...
    async def add_attempt(self, values: dict[str, Any]) -> None: ...
    async def update_attempt(
        self, attempt_id: str, values: dict[str, Any]
    ) -> None: ...
    async def add_audit(self, values: dict[str, Any]) -> None: ...
    async def is_event_processed(self, event_id: str) -> bool: ...
    async def mark_event_processed(
        self, event_id: str, event_type: str, source_agent: str
    ) -> None: ...
    async def find_expired_risk_operations(
        self, before
    ) -> list[str]: ...


class InMemoryOperationRepository:
    """Deterministic adapter for unit tests and local demos."""

    def __init__(self) -> None:
        self.operations: dict[str, OperationRecord] = {}
        self.versions: list[dict[str, Any]] = []
        self.risk_reviews: list[dict[str, Any]] = []
        self.confirmations: list[dict[str, Any]] = []
        self.attempts: list[dict[str, Any]] = []
        self.audits: list[dict[str, Any]] = []
        self.processed_events: set[str] = set()

    async def create(self, record: OperationRecord) -> None:
        if record.operation_id in self.operations:
            raise ValueError("duplicate operation_id")
        self.operations[record.operation_id] = deepcopy(record)

    async def get(self, operation_id: str) -> OperationRecord | None:
        record = self.operations.get(operation_id)
        return deepcopy(record) if record else None

    async def save(self, record: OperationRecord) -> None:
        if record.operation_id not in self.operations:
            raise KeyError(record.operation_id)
        record.updated_at = utc_now()
        self.operations[record.operation_id] = deepcopy(record)

    async def add_version(
        self, record: OperationRecord, changed_by: str
    ) -> None:
        self.versions.append(
            {
                "operation_id": record.operation_id,
                "version": record.version,
                "params_json": deepcopy(record.params),
                "params_hash": record.params_hash,
                "changed_by": changed_by,
                "created_at": utc_now(),
            }
        )

    async def add_risk_review(self, values: dict[str, Any]) -> None:
        self.risk_reviews.append(deepcopy(values))

    async def update_risk_review(
        self, request_event_id: str, values: dict[str, Any]
    ) -> None:
        for item in self.risk_reviews:
            if item["request_event_id"] == request_event_id:
                item.update(deepcopy(values))
                return
        raise KeyError(request_event_id)

    async def add_confirmation(self, values: dict[str, Any]) -> None:
        self.confirmations.append(deepcopy(values))

    async def add_attempt(self, values: dict[str, Any]) -> None:
        self.attempts.append(deepcopy(values))

    async def update_attempt(
        self, attempt_id: str, values: dict[str, Any]
    ) -> None:
        for item in self.attempts:
            if item["attempt_id"] == attempt_id:
                item.update(deepcopy(values))
                return
        raise KeyError(attempt_id)

    async def add_audit(self, values: dict[str, Any]) -> None:
        self.audits.append(deepcopy(values))

    async def is_event_processed(self, event_id: str) -> bool:
        return event_id in self.processed_events

    async def mark_event_processed(
        self, event_id: str, event_type: str, source_agent: str
    ) -> None:
        del event_type, source_agent
        self.processed_events.add(event_id)

    async def find_expired_risk_operations(self, before) -> list[str]:
        return [
            item["operation_id"]
            for item in self.risk_reviews
            if item["status"] == "waiting" and item["expires_at"] <= before
        ]


def _to_record(entity: OperationEntity) -> OperationRecord:
    return OperationRecord(
        operation_id=entity.operation_id,
        request_id=entity.request_id,
        request_event_id=entity.request_event_id,
        source_agent=AgentId(entity.source_agent),
        task_id=entity.task_id,
        session_id=entity.session_id,
        operator_id=entity.operator_id,
        operator_role=entity.operator_role,
        organization_id=entity.organization_id,
        customer_id=entity.customer_id,
        intent=OperationIntent(entity.intent),
        status=OperationStatus(entity.status),
        version=entity.current_version,
        params=entity.params_json or {},
        params_hash=entity.params_hash,
        missing_fields=entity.missing_fields_json or [],
        warnings=entity.warnings_json or [],
        confirmation_required=entity.confirmation_required,
        risk_request_event_id=entity.risk_request_event_id,
        risk_result=entity.risk_result_json,
        result=entity.result_json,
        error_code=entity.error_code,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        completed_at=entity.completed_at,
    )


class SqlAlchemyOperationRepository:
    """MySQL adapter using one AsyncSession per repository operation."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.session_factory = session_factory

    async def create(self, record: OperationRecord) -> None:
        async with self.session_factory() as session:
            session.add(self._to_entity(record))
            await session.commit()

    async def get(self, operation_id: str) -> OperationRecord | None:
        async with self.session_factory() as session:
            result = await session.execute(
                select(OperationEntity).where(
                    OperationEntity.operation_id == operation_id
                )
            )
            entity = result.scalar_one_or_none()
            return _to_record(entity) if entity else None

    async def save(self, record: OperationRecord) -> None:
        async with self.session_factory() as session:
            entity = await self._require_entity(session, record.operation_id)
            entity.status = record.status.value
            entity.current_version = record.version
            entity.params_json = record.params
            entity.params_hash = record.params_hash
            entity.missing_fields_json = record.missing_fields
            entity.warnings_json = record.warnings
            entity.confirmation_required = record.confirmation_required
            entity.risk_request_event_id = record.risk_request_event_id
            entity.risk_result_json = record.risk_result
            entity.result_json = record.result
            entity.error_code = record.error_code
            entity.updated_at = utc_now()
            entity.completed_at = record.completed_at
            await session.commit()

    async def add_version(
        self, record: OperationRecord, changed_by: str
    ) -> None:
        async with self.session_factory() as session:
            session.add(
                OperationVersionEntity(
                    operation_id=record.operation_id,
                    version=record.version,
                    params_json=record.params,
                    params_hash=record.params_hash,
                    changed_by=changed_by,
                    created_at=utc_now(),
                )
            )
            await session.commit()

    async def add_risk_review(self, values: dict[str, Any]) -> None:
        async with self.session_factory() as session:
            session.add(RiskReviewEntity(**values))
            await session.commit()

    async def update_risk_review(
        self, request_event_id: str, values: dict[str, Any]
    ) -> None:
        async with self.session_factory() as session:
            result = await session.execute(
                select(RiskReviewEntity).where(
                    RiskReviewEntity.request_event_id == request_event_id
                )
            )
            entity = result.scalar_one()
            for key, value in values.items():
                setattr(entity, key, value)
            await session.commit()

    async def add_confirmation(self, values: dict[str, Any]) -> None:
        async with self.session_factory() as session:
            session.add(ConfirmationEntity(**values))
            await session.commit()

    async def add_attempt(self, values: dict[str, Any]) -> None:
        async with self.session_factory() as session:
            session.add(ExecutionAttemptEntity(**values))
            await session.commit()

    async def update_attempt(
        self, attempt_id: str, values: dict[str, Any]
    ) -> None:
        async with self.session_factory() as session:
            result = await session.execute(
                select(ExecutionAttemptEntity).where(
                    ExecutionAttemptEntity.attempt_id == attempt_id
                )
            )
            entity = result.scalar_one()
            for key, value in values.items():
                setattr(entity, key, value)
            await session.commit()

    async def add_audit(self, values: dict[str, Any]) -> None:
        async with self.session_factory() as session:
            session.add(AuditLogEntity(**values))
            await session.commit()

    async def is_event_processed(self, event_id: str) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(
                select(ProcessedEventEntity.id).where(
                    ProcessedEventEntity.event_id == event_id
                )
            )
            return result.scalar_one_or_none() is not None

    async def mark_event_processed(
        self, event_id: str, event_type: str, source_agent: str
    ) -> None:
        async with self.session_factory() as session:
            session.add(
                ProcessedEventEntity(
                    event_id=event_id,
                    event_type=event_type,
                    source_agent=source_agent,
                    processed_at=utc_now(),
                )
            )
            await session.commit()

    async def find_expired_risk_operations(self, before) -> list[str]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(RiskReviewEntity.operation_id).where(
                    RiskReviewEntity.status == "waiting",
                    RiskReviewEntity.expires_at <= before,
                )
            )
            return list(result.scalars().all())

    @staticmethod
    async def _require_entity(
        session: AsyncSession,
        operation_id: str,
    ) -> OperationEntity:
        result = await session.execute(
            select(OperationEntity).where(
                OperationEntity.operation_id == operation_id
            )
        )
        return result.scalar_one()

    @staticmethod
    def _to_entity(record: OperationRecord) -> OperationEntity:
        return OperationEntity(
            operation_id=record.operation_id,
            request_id=record.request_id,
            request_event_id=record.request_event_id,
            source_agent=record.source_agent.value,
            task_id=record.task_id,
            session_id=record.session_id,
            operator_id=record.operator_id,
            operator_role=record.operator_role,
            organization_id=record.organization_id,
            customer_id=record.customer_id,
            intent=record.intent.value,
            status=record.status.value,
            current_version=record.version,
            params_json=record.params,
            params_hash=record.params_hash,
            missing_fields_json=record.missing_fields,
            warnings_json=record.warnings,
            confirmation_required=record.confirmation_required,
            risk_request_event_id=record.risk_request_event_id,
            risk_result_json=record.risk_result,
            result_json=record.result,
            error_code=record.error_code,
            created_at=record.created_at,
            updated_at=record.updated_at,
            completed_at=record.completed_at,
        )
