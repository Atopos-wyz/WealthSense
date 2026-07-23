from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.entities.operation import Base


class MockAccountEntity(Base):
    __tablename__ = "operator_mock_accounts"
    __table_args__ = (
        UniqueConstraint("account_no", name="uq_operator_mock_account_no"),
        Index(
            "ix_operator_mock_account_customer",
            "organization_id",
            "customer_id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_no: Mapped[str] = mapped_column(String(64), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="CNY")
    available_balance: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MockHoldingChangeEntity(Base):
    __tablename__ = "operator_mock_holding_changes"
    __table_args__ = (
        UniqueConstraint("change_id", name="uq_operator_mock_holding_change"),
        Index(
            "ix_operator_mock_holding_current",
            "organization_id",
            "holding_no",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    change_id: Mapped[str] = mapped_column(String(64), nullable=False)
    operation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    account_no: Mapped[str] = mapped_column(String(64), nullable=False)
    product_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    holding_no: Mapped[str] = mapped_column(String(64), nullable=False)
    base_holding_id: Mapped[int | None] = mapped_column(BigInteger)
    change_type: Mapped[str] = mapped_column(String(16), nullable=False)
    shares_delta: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MockTransactionEntity(Base):
    __tablename__ = "operator_mock_transactions"
    __table_args__ = (
        UniqueConstraint(
            "transaction_no",
            name="uq_operator_mock_transaction_no",
        ),
        UniqueConstraint(
            "operation_id",
            name="uq_operator_mock_transaction_operation",
        ),
        Index(
            "ix_operator_mock_transaction_customer",
            "organization_id",
            "customer_id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    transaction_no: Mapped[str] = mapped_column(String(64), nullable=False)
    operation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(32), nullable=False)
    from_account_no: Mapped[str | None] = mapped_column(String(64))
    to_account_no: Mapped[str | None] = mapped_column(String(64))
    product_id: Mapped[int | None] = mapped_column(BigInteger)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    shares: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MockProductDetailEntity(Base):
    __tablename__ = "operator_mock_product_details"
    __table_args__ = (
        UniqueConstraint("product_id", name="uq_operator_mock_product_detail"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    net_value: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    minimum_purchase_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="CNY")
    redeemable: Mapped[bool] = mapped_column(nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MockProfileUpdateEntity(Base):
    __tablename__ = "operator_mock_profile_updates"
    __table_args__ = (
        UniqueConstraint("update_no", name="uq_operator_mock_profile_update"),
        UniqueConstraint(
            "operation_id",
            name="uq_operator_mock_profile_operation",
        ),
        Index(
            "ix_operator_mock_profile_latest",
            "organization_id",
            "customer_id",
            "field_name",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    update_no: Mapped[str] = mapped_column(String(64), nullable=False)
    operation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    field_name: Mapped[str] = mapped_column(String(32), nullable=False)
    old_value: Mapped[str | None] = mapped_column(String(500))
    new_value: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MockRiskAssessmentEntity(Base):
    __tablename__ = "operator_mock_risk_assessments"
    __table_args__ = (
        UniqueConstraint(
            "assessment_no",
            name="uq_operator_mock_assessment_no",
        ),
        UniqueConstraint(
            "operation_id",
            name="uq_operator_mock_assessment_operation",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    assessment_no: Mapped[str] = mapped_column(String(64), nullable=False)
    operation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    questionnaire_version: Mapped[str] = mapped_column(String(64), nullable=False)
    answers_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    risk_level: Mapped[str | None] = mapped_column(String(16))
    total_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    valid_until: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MockSuspiciousReportEntity(Base):
    __tablename__ = "operator_mock_suspicious_reports"
    __table_args__ = (
        UniqueConstraint("report_no", name="uq_operator_mock_report_no"),
        UniqueConstraint(
            "operation_id",
            name="uq_operator_mock_report_operation",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    report_no: Mapped[str] = mapped_column(String(64), nullable=False)
    operation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    transaction_no: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs_json: Mapped[list] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MockWorkOrderEntity(Base):
    __tablename__ = "operator_mock_work_orders"
    __table_args__ = (
        UniqueConstraint(
            "work_order_no",
            name="uq_operator_mock_work_order_no",
        ),
        UniqueConstraint(
            "operation_id",
            name="uq_operator_mock_work_order_operation",
        ),
        Index(
            "ix_operator_mock_work_order_customer",
            "organization_id",
            "customer_id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    work_order_no: Mapped[str] = mapped_column(String(64), nullable=False)
    operation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    work_order_type: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MockApiExecutionEntity(Base):
    __tablename__ = "operator_mock_api_executions"
    __table_args__ = (
        UniqueConstraint(
            "operation_id",
            name="uq_operator_mock_api_operation",
        ),
        UniqueConstraint(
            "idempotency_key",
            name="uq_operator_mock_api_idempotency",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    operation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    intent: Mapped[str] = mapped_column(String(64), nullable=False)
    request_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    response_json: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
