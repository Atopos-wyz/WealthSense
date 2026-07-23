from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.entities import (
    MockAccountEntity,
    MockApiExecutionEntity,
    MockHoldingChangeEntity,
    MockProductDetailEntity,
    MockProfileUpdateEntity,
    MockRiskAssessmentEntity,
    MockSuspiciousReportEntity,
    MockTransactionEntity,
    MockWorkOrderEntity,
)
from app.models.schemas.common import OperationIntent, utc_now

MONEY_QUANTUM = Decimal("0.01")
SHARE_QUANTUM = Decimal("0.000001")
ACTIVE_PRODUCT_STATUSES = {"active", "on_sale", "onsale", "enabled", "在售"}
ACTIVE_ACCOUNT_STATUSES = {"active", "enabled", "normal", "正常"}
PRODUCT_FIELD_WHITELIST = {
    "product_id",
    "name",
    "status",
    "net_value",
    "product_type",
    "risk_level",
    "minimum_purchase_amount",
    "currency",
    "redeemable",
}


class MockBusinessError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class MockBusinessPending(RuntimeError):
    pass


class MockBusinessRepository(Protocol):
    async def execute(
        self,
        intent: OperationIntent,
        operation_id: str,
        params: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]: ...

    async def get_status(self, operation_id: str) -> dict[str, Any] | None: ...

    async def seed_defaults(
        self,
        organization_id: str = "ORG001",
        limit: int = 3,
    ) -> dict[str, int]: ...


@dataclass(frozen=True, slots=True)
class CustomerRef:
    id: int
    user_no: str | None
    status: str
    phone: str | None
    email: str | None


@dataclass(frozen=True, slots=True)
class ProductRef:
    id: int
    product_code: str
    product_name: str
    product_type: str
    risk_level: str | None
    status: str
    net_value: Decimal
    minimum_purchase_amount: Decimal
    currency: str
    redeemable: bool


@dataclass(frozen=True, slots=True)
class HoldingRef:
    holding_no: str
    customer_id: int
    product_id: int
    account_no: str
    base_holding_id: int | None
    shares: Decimal


def _new_number(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:20].upper()}"


def _money(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _shares(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(SHARE_QUANTUM, rounding=ROUND_DOWN)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _numeric_candidate(external_id: Any, prefix: str) -> int | None:
    value = str(external_id).strip()
    if value.upper().startswith(prefix.upper()):
        value = value[len(prefix) :]
    value = value.lstrip("_-")
    return int(value) if value.isdigit() else None


class SqlAlchemyMockBusinessRepository:
    """Database-backed implementation of the eight mock business operations."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.session_factory = session_factory

    async def execute(
        self,
        intent: OperationIntent,
        operation_id: str,
        params: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        existing = await self._get_execution_by_key(idempotency_key)
        if existing:
            return self._existing_outcome(existing)

        try:
            async with self.session_factory() as session:
                async with session.begin():
                    execution = MockApiExecutionEntity(
                        operation_id=operation_id,
                        idempotency_key=idempotency_key,
                        intent=intent.value,
                        request_json=_json_safe(
                            {
                                key: value
                                for key, value in params.items()
                                if not key.startswith("_")
                            }
                        ),
                        response_json=None,
                        error_code=None,
                        error_message=None,
                        status="executing",
                        started_at=utc_now(),
                        completed_at=None,
                    )
                    session.add(execution)
                    await session.flush()
                    result = await self._dispatch(
                        session,
                        intent,
                        operation_id,
                        dict(params),
                    )
                    safe_result = _json_safe(result)
                    execution.response_json = safe_result
                    execution.status = "succeeded"
                    execution.completed_at = utc_now()
                return safe_result
        except IntegrityError:
            existing = await self._get_execution_by_key(idempotency_key)
            if not existing:
                existing = await self._get_execution_by_operation(operation_id)
            if not existing:
                raise
            return self._existing_outcome(existing)
        except MockBusinessError as exc:
            await self._record_failure(
                operation_id,
                idempotency_key,
                intent,
                params,
                exc,
            )
            raise

    async def get_status(self, operation_id: str) -> dict[str, Any] | None:
        async with self.session_factory() as session:
            execution = await session.scalar(
                select(MockApiExecutionEntity).where(
                    MockApiExecutionEntity.operation_id == operation_id
                )
            )
        if not execution or execution.status != "succeeded":
            return None
        return dict(execution.response_json or {})

    async def seed_defaults(
        self,
        organization_id: str = "ORG001",
        limit: int = 3,
    ) -> dict[str, int]:
        if limit < 1:
            return {"accounts_created": 0, "product_details_created": 0}
        accounts_created = 0
        product_details_created = 0
        async with self.session_factory() as session:
            async with session.begin():
                customers = (
                    await session.execute(
                        text(
                            """
                            SELECT id
                            FROM sys_user
                            ORDER BY id
                            LIMIT :limit
                            """
                        ),
                        {"limit": limit},
                    )
                ).mappings().all()
                products = (
                    await session.execute(
                        text(
                            """
                            SELECT id
                            FROM fin_product
                            ORDER BY id
                            LIMIT :limit
                            """
                        ),
                        {"limit": limit},
                    )
                ).mappings().all()

                for row in customers:
                    customer_id = int(row["id"])
                    account_no = f"A{customer_id:06d}"
                    exists = await session.scalar(
                        select(MockAccountEntity.id).where(
                            MockAccountEntity.account_no == account_no
                        )
                    )
                    if exists:
                        continue
                    now = utc_now()
                    session.add(
                        MockAccountEntity(
                            account_no=account_no,
                            organization_id=organization_id,
                            customer_id=customer_id,
                            currency="CNY",
                            available_balance=Decimal("1000000.00"),
                            status="active",
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    accounts_created += 1

                for row in products:
                    product_id = int(row["id"])
                    exists = await session.scalar(
                        select(MockProductDetailEntity.id).where(
                            MockProductDetailEntity.product_id == product_id
                        )
                    )
                    if exists:
                        continue
                    session.add(
                        MockProductDetailEntity(
                            product_id=product_id,
                            net_value=Decimal("1.000000"),
                            minimum_purchase_amount=Decimal("1000.00"),
                            currency="CNY",
                            redeemable=True,
                            updated_at=utc_now(),
                        )
                    )
                    product_details_created += 1
        return {
            "accounts_created": accounts_created,
            "product_details_created": product_details_created,
        }

    async def _dispatch(
        self,
        session: AsyncSession,
        intent: OperationIntent,
        operation_id: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        handlers = {
            OperationIntent.PURCHASE: self._purchase,
            OperationIntent.REDEEM: self._redeem,
            OperationIntent.TRANSFER: self._transfer,
            OperationIntent.RISK_REASSESSMENT: self._risk_reassessment,
            OperationIntent.UPDATE_PROFILE: self._update_profile,
            OperationIntent.PRODUCT_QUERY: self._product_query,
            OperationIntent.SUSPICIOUS_REPORT: self._suspicious_report,
            OperationIntent.CREATE_WORK_ORDER: self._create_work_order,
        }
        handler = handlers.get(intent)
        if not handler:
            raise MockBusinessError("OP_INTENT_UNKNOWN", "不支持的业务操作")
        if params.get("simulate_failure"):
            raise MockBusinessError("OP_MOCK_API_FAILED", "Mock 业务接口执行失败")
        amount = params.get("amount")
        if amount is not None and Decimal(str(amount)) > Decimal("10000000"):
            raise MockBusinessError(
                "OP_LIMIT_EXCEEDED",
                "金额超过 Mock 接口限额",
            )
        return await handler(session, operation_id, params)

    async def _purchase(
        self,
        session: AsyncSession,
        operation_id: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        organization_id = str(params.get("_organization_id") or "ORG001")
        customer = await self._resolve_customer(session, params["customer_id"])
        product = await self._resolve_product(session, params["product_id"])
        account = await self._lock_account(
            session,
            organization_id,
            str(params["account_id"]),
            customer.id,
        )
        self._require_active_account(account)
        self._require_active_product(product)
        amount = _money(params["amount"])
        currency = str(params.get("currency") or "CNY").upper()
        self._require_currency(account.currency, currency)
        self._require_currency(product.currency, currency)
        if amount < product.minimum_purchase_amount:
            raise MockBusinessError(
                "OP_MIN_PURCHASE_NOT_MET",
                "申购金额低于产品起购金额",
            )
        if Decimal(account.available_balance) < amount:
            raise MockBusinessError("OP_INSUFFICIENT_BALANCE", "账户可用余额不足")

        shares = _shares(amount / product.net_value)
        if shares <= 0:
            raise MockBusinessError("OP_PARAM_INVALID", "申购金额无法形成有效份额")
        holding_no, base_holding_id = await self._purchase_holding_no(
            session,
            organization_id,
            customer.id,
            product.id,
            account.account_no,
        )
        account.available_balance = _money(
            Decimal(account.available_balance) - amount
        )
        account.updated_at = utc_now()
        session.add(
            MockHoldingChangeEntity(
                change_id=_new_number("HC"),
                operation_id=operation_id,
                organization_id=organization_id,
                customer_id=customer.id,
                account_no=account.account_no,
                product_id=product.id,
                holding_no=holding_no,
                base_holding_id=base_holding_id,
                change_type="purchase",
                shares_delta=shares,
                amount=amount,
                created_at=utc_now(),
            )
        )
        transaction_no = _new_number("TX")
        now = utc_now()
        session.add(
            MockTransactionEntity(
                transaction_no=transaction_no,
                operation_id=operation_id,
                organization_id=organization_id,
                customer_id=customer.id,
                transaction_type="purchase",
                from_account_no=account.account_no,
                to_account_no=None,
                product_id=product.id,
                amount=amount,
                shares=shares,
                currency=currency,
                status="succeeded",
                created_at=now,
                completed_at=now,
            )
        )
        return {
            "operation_id": operation_id,
            "action": OperationIntent.PURCHASE.value,
            "status": "succeeded",
            "transaction_id": transaction_no,
            "holding_id": holding_no,
            "amount": str(amount),
            "shares": str(shares),
            "currency": currency,
        }

    async def _redeem(
        self,
        session: AsyncSession,
        operation_id: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        organization_id = str(params.get("_organization_id") or "ORG001")
        customer = await self._resolve_customer(session, params["customer_id"])
        holding = await self._resolve_holding(
            session,
            organization_id,
            str(params["holding_id"]),
        )
        if holding.customer_id != customer.id:
            raise MockBusinessError(
                "OP_HOLDING_NOT_FOUND",
                "客户名下不存在该持仓",
            )
        product = await self._resolve_product(session, holding.product_id)
        if not product.redeemable:
            raise MockBusinessError("OP_PRODUCT_INACTIVE", "产品当前不可赎回")
        account = await self._lock_account(
            session,
            organization_id,
            holding.account_no,
            customer.id,
        )
        self._require_active_account(account)
        redeem_type = str(params["redeem_type"])
        requested_shares = (
            holding.shares
            if redeem_type == "all"
            else _shares(params["shares"])
        )
        if requested_shares <= 0 or requested_shares > holding.shares:
            raise MockBusinessError("OP_INSUFFICIENT_SHARES", "可赎回份额不足")

        amount = _money(requested_shares * product.net_value)
        account.available_balance = _money(
            Decimal(account.available_balance) + amount
        )
        account.updated_at = utc_now()
        session.add(
            MockHoldingChangeEntity(
                change_id=_new_number("HC"),
                operation_id=operation_id,
                organization_id=organization_id,
                customer_id=customer.id,
                account_no=account.account_no,
                product_id=product.id,
                holding_no=holding.holding_no,
                base_holding_id=holding.base_holding_id,
                change_type="redeem",
                shares_delta=-requested_shares,
                amount=amount,
                created_at=utc_now(),
            )
        )
        transaction_no = _new_number("TX")
        now = utc_now()
        session.add(
            MockTransactionEntity(
                transaction_no=transaction_no,
                operation_id=operation_id,
                organization_id=organization_id,
                customer_id=customer.id,
                transaction_type="redeem",
                from_account_no=None,
                to_account_no=account.account_no,
                product_id=product.id,
                amount=amount,
                shares=requested_shares,
                currency=account.currency,
                status="succeeded",
                created_at=now,
                completed_at=now,
            )
        )
        return {
            "operation_id": operation_id,
            "action": OperationIntent.REDEEM.value,
            "status": "succeeded",
            "transaction_id": transaction_no,
            "holding_id": holding.holding_no,
            "amount": str(amount),
            "shares": str(requested_shares),
            "currency": account.currency,
        }

    async def _transfer(
        self,
        session: AsyncSession,
        operation_id: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        organization_id = str(params.get("_organization_id") or "ORG001")
        customer = await self._resolve_customer(session, params["customer_id"])
        from_no = str(params["from_account_id"])
        to_no = str(params["to_account_id"])
        if from_no == to_no:
            raise MockBusinessError(
                "OP_PARAM_INVALID",
                "转出账户和转入账户不能相同",
            )
        accounts = await self._lock_accounts(
            session,
            organization_id,
            [from_no, to_no],
        )
        from_account = accounts.get(from_no)
        to_account = accounts.get(to_no)
        if not from_account or from_account.customer_id != customer.id:
            raise MockBusinessError("OP_ACCOUNT_NOT_FOUND", "转出账户不存在")
        if not to_account:
            raise MockBusinessError("OP_ACCOUNT_NOT_FOUND", "转入账户不存在")
        self._require_active_account(from_account)
        self._require_active_account(to_account)
        amount = _money(params["amount"])
        currency = str(params.get("currency") or "CNY").upper()
        self._require_currency(from_account.currency, currency)
        self._require_currency(to_account.currency, currency)
        if Decimal(from_account.available_balance) < amount:
            raise MockBusinessError("OP_INSUFFICIENT_BALANCE", "账户可用余额不足")

        from_account.available_balance = _money(
            Decimal(from_account.available_balance) - amount
        )
        to_account.available_balance = _money(
            Decimal(to_account.available_balance) + amount
        )
        now = utc_now()
        from_account.updated_at = now
        to_account.updated_at = now
        transaction_no = _new_number("TX")
        session.add(
            MockTransactionEntity(
                transaction_no=transaction_no,
                operation_id=operation_id,
                organization_id=organization_id,
                customer_id=customer.id,
                transaction_type="transfer",
                from_account_no=from_no,
                to_account_no=to_no,
                product_id=None,
                amount=amount,
                shares=None,
                currency=currency,
                status="succeeded",
                created_at=now,
                completed_at=now,
            )
        )
        return {
            "operation_id": operation_id,
            "action": OperationIntent.TRANSFER.value,
            "status": "succeeded",
            "transaction_id": transaction_no,
            "from_account_id": from_no,
            "to_account_id": to_no,
            "amount": str(amount),
            "currency": currency,
        }

    async def _risk_reassessment(
        self,
        session: AsyncSession,
        operation_id: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        organization_id = str(params.get("_organization_id") or "ORG001")
        customer = await self._resolve_customer(session, params["customer_id"])
        assessment_no = _new_number("RA")
        session.add(
            MockRiskAssessmentEntity(
                assessment_no=assessment_no,
                operation_id=operation_id,
                organization_id=organization_id,
                customer_id=customer.id,
                questionnaire_version=str(params["questionnaire_version"]),
                answers_json=_json_safe(params["answers"]),
                status="submitted",
                risk_level=None,
                total_score=None,
                valid_until=None,
                created_at=utc_now(),
            )
        )
        return {
            "operation_id": operation_id,
            "action": OperationIntent.RISK_REASSESSMENT.value,
            "status": "succeeded",
            "assessment_id": assessment_no,
            "assessment_status": "submitted",
        }

    async def _update_profile(
        self,
        session: AsyncSession,
        operation_id: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        organization_id = str(params.get("_organization_id") or "ORG001")
        customer = await self._resolve_customer(session, params["customer_id"])
        field_name = str(params["field_name"])
        if field_name not in {"phone", "email", "address"}:
            raise MockBusinessError("OP_PARAM_INVALID", "不允许更新该客户字段")
        old_value = await self._effective_profile_value(
            session,
            organization_id,
            customer,
            field_name,
        )
        update_no = _new_number("PU")
        session.add(
            MockProfileUpdateEntity(
                update_no=update_no,
                operation_id=operation_id,
                organization_id=organization_id,
                customer_id=customer.id,
                field_name=field_name,
                old_value=old_value,
                new_value=str(params["new_value"]),
                created_at=utc_now(),
            )
        )
        return {
            "operation_id": operation_id,
            "action": OperationIntent.UPDATE_PROFILE.value,
            "status": "succeeded",
            "update_id": update_no,
            "field_name": field_name,
            "new_value": str(params["new_value"]),
        }

    async def _product_query(
        self,
        session: AsyncSession,
        operation_id: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        product = await self._resolve_product(session, params["product_id"])
        requested_fields = list(params.get("fields") or ["name", "status", "net_value"])
        unknown_fields = set(requested_fields) - PRODUCT_FIELD_WHITELIST
        if unknown_fields:
            raise MockBusinessError(
                "OP_PARAM_INVALID",
                "产品查询包含不允许的字段",
            )
        values = {
            "product_id": product.product_code,
            "name": product.product_name,
            "status": product.status,
            "net_value": str(product.net_value),
            "product_type": product.product_type,
            "risk_level": product.risk_level,
            "minimum_purchase_amount": str(product.minimum_purchase_amount),
            "currency": product.currency,
            "redeemable": product.redeemable,
        }
        product_result = {
            field: values[field]
            for field in requested_fields
            if field in values
        }
        product_result.setdefault("product_id", product.product_code)
        return {
            "operation_id": operation_id,
            "action": OperationIntent.PRODUCT_QUERY.value,
            "status": "succeeded",
            "product": product_result,
        }

    async def _suspicious_report(
        self,
        session: AsyncSession,
        operation_id: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        organization_id = str(params.get("_organization_id") or "ORG001")
        customer = await self._resolve_customer(session, params["customer_id"])
        transaction_no = str(params["transaction_id"])
        transaction = await session.scalar(
            select(MockTransactionEntity).where(
                MockTransactionEntity.transaction_no == transaction_no,
                MockTransactionEntity.organization_id == organization_id,
                MockTransactionEntity.customer_id == customer.id,
            )
        )
        if not transaction:
            raise MockBusinessError(
                "OP_TRANSACTION_NOT_FOUND",
                "未找到需要上报的交易",
            )
        report_no = _new_number("SR")
        session.add(
            MockSuspiciousReportEntity(
                report_no=report_no,
                operation_id=operation_id,
                organization_id=organization_id,
                customer_id=customer.id,
                transaction_no=transaction_no,
                reason=str(params["reason"]),
                evidence_refs_json=list(params.get("evidence_refs") or []),
                status="submitted",
                created_at=utc_now(),
            )
        )
        return {
            "operation_id": operation_id,
            "action": OperationIntent.SUSPICIOUS_REPORT.value,
            "status": "succeeded",
            "report_id": report_no,
            "report_status": "submitted",
        }

    async def _create_work_order(
        self,
        session: AsyncSession,
        operation_id: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        organization_id = str(params.get("_organization_id") or "ORG001")
        customer = await self._resolve_customer(session, params["customer_id"])
        work_order_no = _new_number("WO")
        now = utc_now()
        session.add(
            MockWorkOrderEntity(
                work_order_no=work_order_no,
                operation_id=operation_id,
                organization_id=organization_id,
                customer_id=customer.id,
                work_order_type=str(params["work_order_type"]),
                description=str(params["description"]),
                priority=str(params.get("priority") or "medium"),
                status="open",
                created_at=now,
                updated_at=now,
            )
        )
        return {
            "operation_id": operation_id,
            "action": OperationIntent.CREATE_WORK_ORDER.value,
            "status": "succeeded",
            "work_order_id": work_order_no,
            "work_order_status": "open",
        }

    async def _resolve_customer(
        self,
        session: AsyncSession,
        external_id: Any,
    ) -> CustomerRef:
        numeric_id = _numeric_candidate(external_id, "C")
        row = (
            await session.execute(
                text(
                    """
                    SELECT id, user_no, status, phone, email
                    FROM sys_user
                    WHERE user_no = :external_id
                       OR (:numeric_id IS NOT NULL AND id = :numeric_id)
                    LIMIT 2
                    """
                ),
                {
                    "external_id": str(external_id),
                    "numeric_id": numeric_id,
                },
            )
        ).mappings().all()
        if not row:
            raise MockBusinessError("OP_CUSTOMER_NOT_FOUND", "客户不存在")
        if len(row) > 1:
            raise MockBusinessError("OP_ENTITY_AMBIGUOUS", "客户标识不唯一")
        value = row[0]
        return CustomerRef(
            id=int(value["id"]),
            user_no=value["user_no"],
            status=str(value["status"]),
            phone=value["phone"],
            email=value["email"],
        )

    async def _resolve_product(
        self,
        session: AsyncSession,
        external_id: Any,
    ) -> ProductRef:
        numeric_id = _numeric_candidate(external_id, "P")
        rows = (
            await session.execute(
                text(
                    """
                    SELECT id, product_code, product_name, product_type,
                           risk_level, status
                    FROM fin_product
                    WHERE product_code = :external_id
                       OR (:numeric_id IS NOT NULL AND id = :numeric_id)
                    LIMIT 2
                    """
                ),
                {
                    "external_id": str(external_id),
                    "numeric_id": numeric_id,
                },
            )
        ).mappings().all()
        if not rows:
            raise MockBusinessError("OP_PRODUCT_NOT_FOUND", "产品不存在")
        if len(rows) > 1:
            raise MockBusinessError("OP_ENTITY_AMBIGUOUS", "产品标识不唯一")
        row = rows[0]
        detail = await session.scalar(
            select(MockProductDetailEntity).where(
                MockProductDetailEntity.product_id == int(row["id"])
            )
        )
        if not detail:
            raise MockBusinessError(
                "OP_PRODUCT_DETAILS_MISSING",
                "产品 Mock 详情尚未初始化",
            )
        return ProductRef(
            id=int(row["id"]),
            product_code=str(row["product_code"]),
            product_name=str(row["product_name"]),
            product_type=str(row["product_type"]),
            risk_level=(
                str(row["risk_level"])
                if row["risk_level"] is not None
                else None
            ),
            status=str(row["status"]),
            net_value=Decimal(detail.net_value),
            minimum_purchase_amount=Decimal(detail.minimum_purchase_amount),
            currency=detail.currency,
            redeemable=bool(detail.redeemable),
        )

    async def _lock_account(
        self,
        session: AsyncSession,
        organization_id: str,
        account_no: str,
        customer_id: int | None = None,
    ) -> MockAccountEntity:
        account = await session.scalar(
            select(MockAccountEntity)
            .where(
                MockAccountEntity.organization_id == organization_id,
                MockAccountEntity.account_no == account_no,
            )
            .with_for_update()
        )
        if not account or (
            customer_id is not None and account.customer_id != customer_id
        ):
            raise MockBusinessError("OP_ACCOUNT_NOT_FOUND", "账户不存在")
        return account

    async def _lock_accounts(
        self,
        session: AsyncSession,
        organization_id: str,
        account_numbers: list[str],
    ) -> dict[str, MockAccountEntity]:
        ordered = sorted(set(account_numbers))
        accounts = (
            await session.scalars(
                select(MockAccountEntity)
                .where(
                    MockAccountEntity.organization_id == organization_id,
                    MockAccountEntity.account_no.in_(ordered),
                )
                .order_by(MockAccountEntity.account_no)
                .with_for_update()
            )
        ).all()
        return {account.account_no: account for account in accounts}

    async def _purchase_holding_no(
        self,
        session: AsyncSession,
        organization_id: str,
        customer_id: int,
        product_id: int,
        account_no: str,
    ) -> tuple[str, int | None]:
        base = (
            await session.execute(
                text(
                    """
                    SELECT id
                    FROM fin_holdings
                    WHERE customer_id = :customer_id
                      AND product_id = :product_id
                    ORDER BY id
                    LIMIT 1
                    """
                ),
                {"customer_id": customer_id, "product_id": product_id},
            )
        ).mappings().first()
        if base:
            base_id = int(base["id"])
            return f"H{base_id}", base_id
        existing = await session.scalar(
            select(MockHoldingChangeEntity)
            .where(
                MockHoldingChangeEntity.organization_id == organization_id,
                MockHoldingChangeEntity.customer_id == customer_id,
                MockHoldingChangeEntity.product_id == product_id,
                MockHoldingChangeEntity.account_no == account_no,
            )
            .order_by(MockHoldingChangeEntity.id.desc())
            .limit(1)
        )
        if existing:
            return existing.holding_no, existing.base_holding_id
        return _new_number("MH"), None

    async def _resolve_holding(
        self,
        session: AsyncSession,
        organization_id: str,
        holding_no: str,
    ) -> HoldingRef:
        normalized = holding_no.upper()
        base_id = (
            None
            if normalized.startswith("MH_")
            else _numeric_candidate(normalized, "H")
        )
        base_shares = Decimal("0")
        customer_id: int | None = None
        product_id: int | None = None
        account_no: str | None = None
        if base_id is not None:
            base = (
                await session.execute(
                    text(
                        """
                        SELECT id, customer_id, product_id, shares
                        FROM fin_holdings
                        WHERE id = :holding_id
                        LIMIT 1
                        """
                    ),
                    {"holding_id": base_id},
                )
            ).mappings().first()
            if not base:
                raise MockBusinessError("OP_HOLDING_NOT_FOUND", "持仓不存在")
            customer_id = int(base["customer_id"])
            product_id = int(base["product_id"])
            base_shares = Decimal(base["shares"])
            account = await session.scalar(
                select(MockAccountEntity)
                .where(
                    MockAccountEntity.organization_id == organization_id,
                    MockAccountEntity.customer_id == customer_id,
                )
                .order_by(MockAccountEntity.id)
                .with_for_update()
                .limit(1)
            )
            if not account:
                raise MockBusinessError("OP_ACCOUNT_NOT_FOUND", "持仓结算账户不存在")
            account_no = account.account_no

        first_change = await session.scalar(
            select(MockHoldingChangeEntity)
            .where(
                MockHoldingChangeEntity.organization_id == organization_id,
                MockHoldingChangeEntity.holding_no == normalized,
            )
            .order_by(MockHoldingChangeEntity.id)
            .with_for_update()
            .limit(1)
        )
        if first_change:
            customer_id = first_change.customer_id
            product_id = first_change.product_id
            account_no = first_change.account_no
            base_id = first_change.base_holding_id
        if customer_id is None or product_id is None or account_no is None:
            raise MockBusinessError("OP_HOLDING_NOT_FOUND", "持仓不存在")
        await self._lock_account(
            session,
            organization_id,
            account_no,
            customer_id,
        )
        delta = await session.scalar(
            select(
                func.coalesce(
                    func.sum(MockHoldingChangeEntity.shares_delta),
                    Decimal("0"),
                )
            ).where(
                MockHoldingChangeEntity.organization_id == organization_id,
                MockHoldingChangeEntity.holding_no == normalized,
            )
        )
        current_shares = _shares(base_shares + Decimal(delta or 0))
        if current_shares <= 0:
            raise MockBusinessError("OP_INSUFFICIENT_SHARES", "持仓已清仓")
        return HoldingRef(
            holding_no=normalized,
            customer_id=customer_id,
            product_id=product_id,
            account_no=account_no,
            base_holding_id=base_id,
            shares=current_shares,
        )

    async def _effective_profile_value(
        self,
        session: AsyncSession,
        organization_id: str,
        customer: CustomerRef,
        field_name: str,
    ) -> str | None:
        latest = await session.scalar(
            select(MockProfileUpdateEntity)
            .where(
                MockProfileUpdateEntity.organization_id == organization_id,
                MockProfileUpdateEntity.customer_id == customer.id,
                MockProfileUpdateEntity.field_name == field_name,
            )
            .order_by(MockProfileUpdateEntity.id.desc())
            .limit(1)
        )
        if latest:
            return latest.new_value
        if field_name == "phone":
            return customer.phone
        if field_name == "email":
            return customer.email
        return None

    async def _get_execution_by_key(
        self,
        idempotency_key: str,
    ) -> MockApiExecutionEntity | None:
        async with self.session_factory() as session:
            return await session.scalar(
                select(MockApiExecutionEntity).where(
                    MockApiExecutionEntity.idempotency_key == idempotency_key
                )
            )

    async def _get_execution_by_operation(
        self,
        operation_id: str,
    ) -> MockApiExecutionEntity | None:
        async with self.session_factory() as session:
            return await session.scalar(
                select(MockApiExecutionEntity).where(
                    MockApiExecutionEntity.operation_id == operation_id
                )
            )

    async def _record_failure(
        self,
        operation_id: str,
        idempotency_key: str,
        intent: OperationIntent,
        params: dict[str, Any],
        error: MockBusinessError,
    ) -> None:
        try:
            async with self.session_factory() as session:
                async with session.begin():
                    session.add(
                        MockApiExecutionEntity(
                            operation_id=operation_id,
                            idempotency_key=idempotency_key,
                            intent=intent.value,
                            request_json=_json_safe(
                                {
                                    key: value
                                    for key, value in params.items()
                                    if not key.startswith("_")
                                }
                            ),
                            response_json=None,
                            error_code=error.code,
                            error_message=error.message,
                            status="failed",
                            started_at=utc_now(),
                            completed_at=utc_now(),
                        )
                    )
        except IntegrityError:
            return

    @staticmethod
    def _existing_outcome(
        execution: MockApiExecutionEntity,
    ) -> dict[str, Any]:
        if execution.status == "succeeded":
            return dict(execution.response_json or {})
        if execution.status == "failed":
            raise MockBusinessError(
                execution.error_code or "OP_MOCK_API_FAILED",
                execution.error_message or "Mock 业务接口执行失败",
            )
        raise MockBusinessPending("Mock 业务操作仍在执行")

    @staticmethod
    def _require_active_account(account: MockAccountEntity) -> None:
        if account.status.lower() not in ACTIVE_ACCOUNT_STATUSES:
            raise MockBusinessError("OP_ACCOUNT_FROZEN", "账户已冻结或不可用")

    @staticmethod
    def _require_active_product(product: ProductRef) -> None:
        if product.status.lower() not in ACTIVE_PRODUCT_STATUSES:
            raise MockBusinessError("OP_PRODUCT_INACTIVE", "产品已停售或不可用")

    @staticmethod
    def _require_currency(actual: str, expected: str) -> None:
        if actual.upper() != expected.upper():
            raise MockBusinessError("OP_CURRENCY_MISMATCH", "账户或产品币种不匹配")
