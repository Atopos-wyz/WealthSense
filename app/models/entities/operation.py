from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class OperationEntity(Base):
    __tablename__ = "operations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    operation_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    request_event_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    source_agent: Mapped[str] = mapped_column(String(32), index=True)
    task_id: Mapped[str | None] = mapped_column(String(64), index=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    operator_id: Mapped[str] = mapped_column(String(64), index=True)
    operator_role: Mapped[str] = mapped_column(String(32))
    organization_id: Mapped[str] = mapped_column(String(64), index=True)
    customer_id: Mapped[str | None] = mapped_column(String(64), index=True)
    intent: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(64), index=True)
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    params_json: Mapped[dict] = mapped_column(JSON, default=dict)
    params_hash: Mapped[str] = mapped_column(String(64))
    missing_fields_json: Mapped[list] = mapped_column(JSON, default=list)
    warnings_json: Mapped[list] = mapped_column(JSON, default=list)
    confirmation_required: Mapped[bool] = mapped_column(Boolean, default=False)
    risk_request_event_id: Mapped[str | None] = mapped_column(String(64), index=True)
    risk_result_json: Mapped[dict | None] = mapped_column(JSON)
    result_json: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OperationVersionEntity(Base):
    __tablename__ = "operation_versions"
    __table_args__ = (UniqueConstraint("operation_id", "version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    operation_id: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer)
    params_json: Mapped[dict] = mapped_column(JSON)
    params_hash: Mapped[str] = mapped_column(String(64))
    changed_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RiskReviewEntity(Base):
    __tablename__ = "risk_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    operation_id: Mapped[str] = mapped_column(String(64), index=True)
    operation_version: Mapped[int] = mapped_column(Integer)
    request_event_id: Mapped[str] = mapped_column(String(64), unique=True)
    result_event_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    decision: Mapped[str | None] = mapped_column(String(32))
    risk_level: Mapped[str | None] = mapped_column(String(32))
    rule_hits_json: Mapped[list] = mapped_column(JSON, default=list)
    warnings_json: Mapped[list] = mapped_column(JSON, default=list)
    reason: Mapped[str] = mapped_column(Text, default="")
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConfirmationEntity(Base):
    __tablename__ = "operation_confirmations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    operation_id: Mapped[str] = mapped_column(String(64), index=True)
    operation_version: Mapped[int] = mapped_column(Integer)
    params_hash: Mapped[str] = mapped_column(String(64))
    confirmed_by: Mapped[str] = mapped_column(String(64))
    confirmation_method: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ExecutionAttemptEntity(Base):
    __tablename__ = "execution_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    attempt_id: Mapped[str] = mapped_column(String(64), unique=True)
    operation_id: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    tool_name: Mapped[str] = mapped_column(String(64))
    request_json: Mapped[dict] = mapped_column(JSON)
    response_json: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLogEntity(Base):
    __tablename__ = "operation_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    operation_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    actor_type: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[str] = mapped_column(String(64))
    old_status: Mapped[str | None] = mapped_column(String(64))
    new_status: Mapped[str | None] = mapped_column(String(64))
    detail_json: Mapped[dict] = mapped_column(JSON, default=dict)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProcessedEventEntity(Base):
    __tablename__ = "processed_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    source_agent: Mapped[str] = mapped_column(String(32))
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

