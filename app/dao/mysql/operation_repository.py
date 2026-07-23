from copy import deepcopy
from datetime import timedelta
from typing import Any, Protocol

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.entities import (
    AuditLogEntity,
    ConfirmationEntity,
    ExecutionAttemptEntity,
    OperationEntity,
    OperationVersionEntity,
    OutboxEventEntity,
    ProcessedEventEntity,
    RiskReviewEntity,
)
from app.models.schemas.common import AgentId, OperationIntent, OperationStatus, utc_now
from app.models.schemas.internal import OperationRecord


class OperationRepository(Protocol):
    async def create(self, record: OperationRecord) -> None: ...
    async def get(self, operation_id: str) -> OperationRecord | None: ...
    async def get_by_request(
        self,
        source_agent: str,
        operator_id: str,
        organization_id: str,
        request_id: str,
    ) -> OperationRecord | None: ...
    async def save(self, record: OperationRecord) -> None: ...
    async def transition(
        self,
        record: OperationRecord,
        expected_status: OperationStatus,
        target_status: OperationStatus,
        expected_version: int,
        expected_risk_request_id: str | None = None,
        audit_values: dict[str, Any] | None = None,
        outbox_values: list[dict[str, Any]] | None = None,
        execution_attempt_values: dict[str, Any] | None = None,
    ) -> bool: ...
    async def set_risk_request(
        self,
        operation_id: str,
        version: int,
        request_event_id: str,
    ) -> bool: ...
    async def prepare_risk_review(
        self,
        operation_id: str,
        version: int,
        request_event_id: str,
        review_values: dict[str, Any],
        outbox_values: dict[str, Any],
    ) -> bool: ...
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
    async def update_attempt_by_idempotency(
        self, idempotency_key: str, values: dict[str, Any]
    ) -> bool: ...
    async def add_audit(self, values: dict[str, Any]) -> None: ...
    async def is_event_processed(self, event_id: str) -> bool: ...
    async def mark_event_processed(
        self, event_id: str, event_type: str, source_agent: str
    ) -> None: ...
    async def claim_event(
        self,
        event_id: str,
        event_type: str,
        source_agent: str,
        lease_seconds: int = 30,
    ) -> bool: ...
    async def complete_event(self, event_id: str) -> None: ...
    async def find_expired_risk_operations(
        self, before
    ) -> list[str]: ...
    async def find_expired_confirmations(self, before) -> list[str]: ...
    async def find_pending_verification(self) -> list[str]: ...
    async def find_executing(self) -> list[str]: ...
    async def find_risk_approved(self, before) -> list[str]: ...
    async def find_confirmed(self, before) -> list[str]: ...
    async def enqueue_outbox(
        self,
        event_id: str,
        channel: str,
        payload: dict[str, Any],
    ) -> None: ...
    async def mark_outbox_sent(self, event_id: str) -> None: ...
    async def list_pending_outbox(
        self, limit: int = 100
    ) -> list[dict[str, Any]]: ...


class InMemoryOperationRepository:
    """Deterministic adapter for unit tests and local demos."""

    def __init__(self) -> None:
        self.operations: dict[str, OperationRecord] = {}
        self.versions: list[dict[str, Any]] = []
        self.risk_reviews: list[dict[str, Any]] = []
        self.confirmations: list[dict[str, Any]] = []
        self.attempts: list[dict[str, Any]] = []
        self.audits: list[dict[str, Any]] = []
        self.processed_events: dict[str, dict[str, Any]] = {}
        self.outbox: dict[str, dict[str, Any]] = {}

    async def create(self, record: OperationRecord) -> None:
        if record.operation_id in self.operations:
            raise ValueError("duplicate operation_id")
        self.operations[record.operation_id] = deepcopy(record)

    async def get(self, operation_id: str) -> OperationRecord | None:
        record = self.operations.get(operation_id)
        return deepcopy(record) if record else None

    async def get_by_request(
        self,
        source_agent: str,
        operator_id: str,
        organization_id: str,
        request_id: str,
    ) -> OperationRecord | None:
        for record in self.operations.values():
            if (
                record.source_agent.value == source_agent
                and record.operator_id == operator_id
                and record.organization_id == organization_id
                and record.request_id == request_id
            ):
                return deepcopy(record)
        return None

    async def save(self, record: OperationRecord) -> None:
        if record.operation_id not in self.operations:
            raise KeyError(record.operation_id)
        record.updated_at = utc_now()
        self.operations[record.operation_id] = deepcopy(record)

    async def transition(
        self,
        record: OperationRecord,
        expected_status: OperationStatus,
        target_status: OperationStatus,
        expected_version: int,
        expected_risk_request_id: str | None = None,
        audit_values: dict[str, Any] | None = None,
        outbox_values: list[dict[str, Any]] | None = None,
        execution_attempt_values: dict[str, Any] | None = None,
    ) -> bool:
        current = self.operations.get(record.operation_id)
        if (
            not current
            or current.status != expected_status
            or current.version != expected_version
            or (
                expected_risk_request_id is not None
                and current.risk_request_event_id
                != expected_risk_request_id
            )
        ):
            return False
        record.status = target_status
        record.updated_at = utc_now()
        self.operations[record.operation_id] = deepcopy(record)
        if audit_values:
            self.audits.append(deepcopy(audit_values))
        for item in outbox_values or []:
            await self.enqueue_outbox(
                item["event_id"],
                item["channel"],
                item["payload"],
            )
        if execution_attempt_values:
            self.attempts.append(deepcopy(execution_attempt_values))
        return True

    async def set_risk_request(
        self,
        operation_id: str,
        version: int,
        request_event_id: str,
    ) -> bool:
        current = self.operations.get(operation_id)
        if (
            not current
            or current.status != OperationStatus.WAITING_RISK_REVIEW
            or current.version != version
        ):
            return False
        current.risk_request_event_id = request_event_id
        current.updated_at = utc_now()
        return True

    async def prepare_risk_review(
        self,
        operation_id: str,
        version: int,
        request_event_id: str,
        review_values: dict[str, Any],
        outbox_values: dict[str, Any],
    ) -> bool:
        updated = await self.set_risk_request(
            operation_id,
            version,
            request_event_id,
        )
        if not updated:
            return False
        self.risk_reviews.append(deepcopy(review_values))
        await self.enqueue_outbox(
            outbox_values["event_id"],
            outbox_values["channel"],
            outbox_values["payload"],
        )
        return True

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

    async def update_attempt_by_idempotency(
        self, idempotency_key: str, values: dict[str, Any]
    ) -> bool:
        for item in self.attempts:
            if item["idempotency_key"] == idempotency_key:
                item.update(deepcopy(values))
                return True
        return False

    async def add_audit(self, values: dict[str, Any]) -> None:
        self.audits.append(deepcopy(values))

    async def is_event_processed(self, event_id: str) -> bool:
        return event_id in self.processed_events

    async def mark_event_processed(
        self, event_id: str, event_type: str, source_agent: str
    ) -> None:
        del event_type, source_agent
        self.processed_events[event_id] = {
            "status": "completed",
            "lease_expires_at": None,
        }

    async def claim_event(
        self,
        event_id: str,
        event_type: str,
        source_agent: str,
        lease_seconds: int = 30,
    ) -> bool:
        del event_type, source_agent
        now = utc_now()
        existing = self.processed_events.get(event_id)
        if existing:
            lease_expires_at = existing.get("lease_expires_at")
            if (
                existing["status"] != "processing"
                or not lease_expires_at
                or lease_expires_at > now
            ):
                return False
        self.processed_events[event_id] = {
            "status": "processing",
            "lease_expires_at": now + timedelta(seconds=lease_seconds),
        }
        return True

    async def complete_event(self, event_id: str) -> None:
        if event_id not in self.processed_events:
            raise KeyError(event_id)
        self.processed_events[event_id] = {
            "status": "completed",
            "lease_expires_at": None,
        }

    async def find_expired_risk_operations(self, before) -> list[str]:
        return [
            item["operation_id"]
            for item in self.risk_reviews
            if item["status"] == "waiting" and item["expires_at"] <= before
        ]

    async def find_expired_confirmations(self, before) -> list[str]:
        return [
            record.operation_id
            for record in self.operations.values()
            if (
                record.status == OperationStatus.PENDING_CONFIRMATION
                and record.confirmation_expires_at
                and record.confirmation_expires_at <= before
            )
        ]

    async def find_pending_verification(self) -> list[str]:
        return [
            record.operation_id
            for record in self.operations.values()
            if record.status == OperationStatus.PENDING_VERIFICATION
        ]

    async def find_executing(self) -> list[str]:
        return [
            record.operation_id
            for record in self.operations.values()
            if record.status == OperationStatus.EXECUTING
        ]

    async def find_risk_approved(self, before) -> list[str]:
        return [
            record.operation_id
            for record in self.operations.values()
            if (
                record.status == OperationStatus.RISK_APPROVED
                and record.updated_at <= before
            )
        ]

    async def find_confirmed(self, before) -> list[str]:
        return [
            record.operation_id
            for record in self.operations.values()
            if (
                record.status == OperationStatus.CONFIRMED
                and record.updated_at <= before
            )
        ]

    async def enqueue_outbox(
        self,
        event_id: str,
        channel: str,
        payload: dict[str, Any],
    ) -> None:
        self.outbox.setdefault(
            event_id,
            {
                "event_id": event_id,
                "channel": channel,
                "payload": deepcopy(payload),
                "status": "pending",
                "attempts": 0,
                "created_at": utc_now(),
                "sent_at": None,
            },
        )

    async def mark_outbox_sent(self, event_id: str) -> None:
        item = self.outbox[event_id]
        item["status"] = "sent"
        item["attempts"] += 1
        item["sent_at"] = utc_now()

    async def list_pending_outbox(
        self, limit: int = 100
    ) -> list[dict[str, Any]]:
        return [
            deepcopy(item)
            for item in self.outbox.values()
            if item["status"] == "pending"
        ][:limit]


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
        raw_message=entity.raw_message,
        version=entity.current_version,
        params=entity.params_json or {},
        params_hash=entity.params_hash,
        missing_fields=entity.missing_fields_json or [],
        warnings=entity.warnings_json or [],
        confirmation_required=entity.confirmation_required,
        confirmation_expires_at=entity.confirmation_expires_at,
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

    async def get_by_request(
        self,
        source_agent: str,
        operator_id: str,
        organization_id: str,
        request_id: str,
    ) -> OperationRecord | None:
        async with self.session_factory() as session:
            result = await session.execute(
                select(OperationEntity).where(
                    OperationEntity.source_agent == source_agent,
                    OperationEntity.operator_id == operator_id,
                    OperationEntity.organization_id == organization_id,
                    OperationEntity.request_id == request_id,
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
            entity.confirmation_expires_at = record.confirmation_expires_at
            entity.risk_request_event_id = record.risk_request_event_id
            entity.risk_result_json = record.risk_result
            entity.result_json = record.result
            entity.error_code = record.error_code
            entity.updated_at = utc_now()
            entity.completed_at = record.completed_at
            await session.commit()

    async def transition(
        self,
        record: OperationRecord,
        expected_status: OperationStatus,
        target_status: OperationStatus,
        expected_version: int,
        expected_risk_request_id: str | None = None,
        audit_values: dict[str, Any] | None = None,
        outbox_values: list[dict[str, Any]] | None = None,
        execution_attempt_values: dict[str, Any] | None = None,
    ) -> bool:
        record.updated_at = utc_now()
        async with self.session_factory() as session:
            conditions = [
                OperationEntity.operation_id == record.operation_id,
                OperationEntity.status == expected_status.value,
                OperationEntity.current_version == expected_version,
            ]
            if expected_risk_request_id is not None:
                conditions.append(
                    OperationEntity.risk_request_event_id
                    == expected_risk_request_id
                )
            result = await session.execute(
                update(OperationEntity)
                .where(*conditions)
                .values(
                    status=target_status.value,
                    current_version=record.version,
                    params_json=record.params,
                    params_hash=record.params_hash,
                    missing_fields_json=record.missing_fields,
                    warnings_json=record.warnings,
                    confirmation_required=record.confirmation_required,
                    confirmation_expires_at=record.confirmation_expires_at,
                    risk_request_event_id=record.risk_request_event_id,
                    risk_result_json=record.risk_result,
                    result_json=record.result,
                    error_code=record.error_code,
                    updated_at=record.updated_at,
                    completed_at=record.completed_at,
                )
            )
            if result.rowcount and audit_values:
                session.add(AuditLogEntity(**audit_values))
            if result.rowcount:
                for item in outbox_values or []:
                    session.add(
                        OutboxEventEntity(
                            event_id=item["event_id"],
                            channel=item["channel"],
                            payload_json=item["payload"],
                            status="pending",
                            attempts=0,
                            created_at=utc_now(),
                            sent_at=None,
                        )
                    )
                if execution_attempt_values:
                    session.add(
                        ExecutionAttemptEntity(
                            **execution_attempt_values
                        )
                    )
            await session.commit()
            return bool(result.rowcount)

    async def set_risk_request(
        self,
        operation_id: str,
        version: int,
        request_event_id: str,
    ) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(
                update(OperationEntity)
                .where(
                    OperationEntity.operation_id == operation_id,
                    OperationEntity.status
                    == OperationStatus.WAITING_RISK_REVIEW.value,
                    OperationEntity.current_version == version,
                )
                .values(
                    risk_request_event_id=request_event_id,
                    updated_at=utc_now(),
                )
            )
            await session.commit()
            return bool(result.rowcount)

    async def prepare_risk_review(
        self,
        operation_id: str,
        version: int,
        request_event_id: str,
        review_values: dict[str, Any],
        outbox_values: dict[str, Any],
    ) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(
                update(OperationEntity)
                .where(
                    OperationEntity.operation_id == operation_id,
                    OperationEntity.status
                    == OperationStatus.WAITING_RISK_REVIEW.value,
                    OperationEntity.current_version == version,
                )
                .values(
                    risk_request_event_id=request_event_id,
                    updated_at=utc_now(),
                )
            )
            if not result.rowcount:
                await session.rollback()
                return False
            session.add(RiskReviewEntity(**review_values))
            session.add(
                OutboxEventEntity(
                    event_id=outbox_values["event_id"],
                    channel=outbox_values["channel"],
                    payload_json=outbox_values["payload"],
                    status="pending",
                    attempts=0,
                    created_at=utc_now(),
                    sent_at=None,
                )
            )
            await session.commit()
            return True

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

    async def update_attempt_by_idempotency(
        self, idempotency_key: str, values: dict[str, Any]
    ) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(
                update(ExecutionAttemptEntity)
                .where(
                    ExecutionAttemptEntity.idempotency_key
                    == idempotency_key
                )
                .values(**values)
            )
            await session.commit()
            return bool(result.rowcount)

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
                    status="completed",
                    lease_expires_at=None,
                    processed_at=utc_now(),
                )
            )
            await session.commit()

    async def claim_event(
        self,
        event_id: str,
        event_type: str,
        source_agent: str,
        lease_seconds: int = 30,
    ) -> bool:
        now = utc_now()
        lease_expires_at = now + timedelta(seconds=lease_seconds)
        async with self.session_factory() as session:
            reclaimed = await session.execute(
                update(ProcessedEventEntity)
                .where(
                    ProcessedEventEntity.event_id == event_id,
                    ProcessedEventEntity.status == "processing",
                    ProcessedEventEntity.lease_expires_at <= now,
                )
                .values(
                    lease_expires_at=lease_expires_at,
                    processed_at=now,
                )
            )
            if reclaimed.rowcount:
                await session.commit()
                return True
            session.add(
                ProcessedEventEntity(
                    event_id=event_id,
                    event_type=event_type,
                    source_agent=source_agent,
                    status="processing",
                    lease_expires_at=lease_expires_at,
                    processed_at=now,
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return False
            return True

    async def complete_event(self, event_id: str) -> None:
        async with self.session_factory() as session:
            await session.execute(
                update(ProcessedEventEntity)
                .where(ProcessedEventEntity.event_id == event_id)
                .values(
                    status="completed",
                    lease_expires_at=None,
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

    async def find_expired_confirmations(self, before) -> list[str]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(OperationEntity.operation_id).where(
                    OperationEntity.status
                    == OperationStatus.PENDING_CONFIRMATION.value,
                    OperationEntity.confirmation_expires_at.is_not(None),
                    OperationEntity.confirmation_expires_at <= before,
                )
            )
            return list(result.scalars().all())

    async def find_pending_verification(self) -> list[str]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(OperationEntity.operation_id).where(
                    OperationEntity.status
                    == OperationStatus.PENDING_VERIFICATION.value
                )
            )
            return list(result.scalars().all())

    async def find_executing(self) -> list[str]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(OperationEntity.operation_id).where(
                    OperationEntity.status
                    == OperationStatus.EXECUTING.value
                )
            )
            return list(result.scalars().all())

    async def find_risk_approved(self, before) -> list[str]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(OperationEntity.operation_id).where(
                    OperationEntity.status
                    == OperationStatus.RISK_APPROVED.value,
                    OperationEntity.updated_at <= before,
                )
            )
            return list(result.scalars().all())

    async def find_confirmed(self, before) -> list[str]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(OperationEntity.operation_id).where(
                    OperationEntity.status
                    == OperationStatus.CONFIRMED.value,
                    OperationEntity.updated_at <= before,
                )
            )
            return list(result.scalars().all())

    async def enqueue_outbox(
        self,
        event_id: str,
        channel: str,
        payload: dict[str, Any],
    ) -> None:
        async with self.session_factory() as session:
            existing = await session.execute(
                select(OutboxEventEntity.id).where(
                    OutboxEventEntity.event_id == event_id
                )
            )
            if existing.scalar_one_or_none() is None:
                session.add(
                    OutboxEventEntity(
                        event_id=event_id,
                        channel=channel,
                        payload_json=payload,
                        status="pending",
                        attempts=0,
                        created_at=utc_now(),
                        sent_at=None,
                    )
                )
                await session.commit()

    async def mark_outbox_sent(self, event_id: str) -> None:
        async with self.session_factory() as session:
            await session.execute(
                update(OutboxEventEntity)
                .where(OutboxEventEntity.event_id == event_id)
                .values(
                    status="sent",
                    attempts=OutboxEventEntity.attempts + 1,
                    sent_at=utc_now(),
                )
            )
            await session.commit()

    async def list_pending_outbox(
        self, limit: int = 100
    ) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(OutboxEventEntity)
                .where(OutboxEventEntity.status == "pending")
                .order_by(OutboxEventEntity.id)
                .limit(limit)
            )
            return [
                {
                    "event_id": item.event_id,
                    "channel": item.channel,
                    "payload": item.payload_json,
                    "status": item.status,
                    "attempts": item.attempts,
                    "created_at": item.created_at,
                    "sent_at": item.sent_at,
                }
                for item in result.scalars().all()
            ]

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
            raw_message=record.raw_message,
            current_version=record.version,
            params_json=record.params,
            params_hash=record.params_hash,
            missing_fields_json=record.missing_fields,
            warnings_json=record.warnings,
            confirmation_required=record.confirmation_required,
            confirmation_expires_at=record.confirmation_expires_at,
            risk_request_event_id=record.risk_request_event_id,
            risk_result_json=record.risk_result,
            result_json=record.result,
            error_code=record.error_code,
            created_at=record.created_at,
            updated_at=record.updated_at,
            completed_at=record.completed_at,
        )
