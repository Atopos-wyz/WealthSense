import unittest
import asyncio
from datetime import timedelta
import time

from app.event.channels import EventChannel
from app.models.schemas.common import (
    AgentEvent,
    AgentId,
    OperationIntent,
    OperationStatus,
    utc_now,
)
from app.models.schemas.operation import (
    ChatOperationRequest,
    ConfirmOperationRequest,
    OperatorContext,
    UpdateOperationRequest,
)
from app.utils.exceptions import ConflictError
from app.utils.security import encode_hs256_jwt
from tests.helpers import build_test_service


class OperationFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.service, self.repository, self.publisher = build_test_service()
        self.operator = OperatorContext(
            operator_id="EMP001",
            role="advisor",
            organization_id="ORG001",
            allowed_customer_ids={"C001"},
            allowed_account_ids={"A001"},
            allowed_holding_ids={"H001"},
        )

    async def _create_purchase(self):
        return await self.service.create_operation(
            ChatOperationRequest(
                request_id="REQ001",
                session_id="S001",
                customer_id="C001",
                message="为张三申购10万元稳健增利A",
            ),
            self.operator,
            OperationIntent.PURCHASE,
            {
                "customer_id": "C001",
                "product_id": "P001",
                "account_id": "A001",
                "amount": "100000.00",
                "currency": "CNY",
            },
            AgentId.ADVISOR,
        )

    async def _risk_event(self, operation_id: str, decision: str) -> AgentEvent:
        record = await self.repository.get(operation_id)
        assert record is not None
        return AgentEvent(
            event_id=f"EVT_RISK_{decision}",
            event_type="risk.check.completed",
            source_agent=AgentId.RISK,
            target_agents=[AgentId.OPERATOR],
            correlation_id=operation_id,
            operation_id=operation_id,
            payload={
                "operation_version": 1,
                "request_event_id": record.risk_request_event_id,
                "decision": decision,
                "risk_level": "low" if decision == "approved" else "high",
                "rule_hits": [],
                "warnings": [],
                "reason": "test",
            },
            occurred_at=utc_now(),
            expires_at=utc_now() + timedelta(minutes=5),
        )

    async def test_purchase_waits_for_risk_then_confirmation(self) -> None:
        created = await self._create_purchase()
        self.assertEqual(created.status, OperationStatus.WAITING_RISK_REVIEW)
        self.assertTrue(
            any(
                channel == EventChannel.RISK_COMMAND
                and event.event_type == "risk.check.requested"
                for channel, event in self.publisher.events
            )
        )

        risk_result = await self.service.handle_risk_result(
            await self._risk_event(created.operation_id, "approved")
        )
        self.assertEqual(
            risk_result.status,
            OperationStatus.PENDING_CONFIRMATION,
        )

        record = await self.repository.get(created.operation_id)
        assert record is not None
        completed = await self.service.confirm(
            created.operation_id,
            ConfirmOperationRequest(
                request_id="REQ_CONFIRM",
                confirmer_id="C001",
                operation_version=record.version,
                params_hash=record.params_hash,
            ),
        )
        self.assertEqual(completed.status, OperationStatus.SUCCEEDED)
        self.assertIsNotNone(completed.result)
        self.assertTrue(
            any(
                channel == EventChannel.TRANSACTION_EVENT
                and event.event_type == "transaction.created"
                for channel, event in self.publisher.events
            )
        )

    async def test_risk_rejection_prevents_execution(self) -> None:
        created = await self._create_purchase()
        rejected = await self.service.handle_risk_result(
            await self._risk_event(created.operation_id, "rejected")
        )
        self.assertEqual(rejected.status, OperationStatus.RISK_REJECTED)
        self.assertEqual(len(self.repository.attempts), 0)

    async def test_same_request_id_returns_same_operation(self) -> None:
        first = await self._create_purchase()
        second = await self._create_purchase()
        self.assertEqual(first.operation_id, second.operation_id)
        self.assertEqual(len(self.repository.operations), 1)

    async def test_same_request_id_is_isolated_by_authenticated_subject(self) -> None:
        first = await self._create_purchase()
        other_operator = OperatorContext(
            operator_id="EMP002",
            role="advisor",
            organization_id="ORG002",
            allowed_customer_ids={"C002"},
            allowed_account_ids={"A002"},
        )
        second = await self.service.create_operation(
            ChatOperationRequest(
                request_id="REQ001",
                session_id="S002",
                customer_id="C002",
                message="申购",
            ),
            other_operator,
            OperationIntent.PURCHASE,
            {
                "customer_id": "C002",
                "product_id": "P001",
                "account_id": "A002",
                "amount": "100.00",
            },
            AgentId.ADVISOR,
        )
        self.assertNotEqual(first.operation_id, second.operation_id)
        self.assertEqual(len(self.repository.operations), 2)

    async def test_customer_scope_is_enforced(self) -> None:
        response = await self.service.create_operation(
            ChatOperationRequest(
                request_id="REQ_SCOPE",
                session_id="S001",
                customer_id="C002",
                message="申购",
            ),
            self.operator,
            OperationIntent.PURCHASE,
            {
                "customer_id": "C002",
                "product_id": "P001",
                "account_id": "A002",
                "amount": "100.00",
            },
            AgentId.ADVISOR,
        )
        self.assertEqual(response.status, OperationStatus.PERMISSION_DENIED)
        self.assertEqual(response.error.code, "OP_CUSTOMER_OUT_OF_SCOPE")

    async def test_account_must_belong_to_customer(self) -> None:
        response = await self.service.create_operation(
            ChatOperationRequest(
                request_id="REQ_ACCOUNT_SCOPE",
                session_id="S001",
                customer_id="C001",
                message="申购",
            ),
            self.operator,
            OperationIntent.PURCHASE,
            {
                "customer_id": "C001",
                "product_id": "P001",
                "account_id": "A002",
                "amount": "100.00",
            },
            AgentId.ADVISOR,
        )
        self.assertEqual(response.status, OperationStatus.PERMISSION_DENIED)
        self.assertEqual(response.error.code, "OP_ACCOUNT_OUT_OF_SCOPE")

    async def test_duplicate_risk_event_is_rejected(self) -> None:
        created = await self._create_purchase()
        event = await self._risk_event(created.operation_id, "approved")
        await self.service.handle_risk_result(event)
        with self.assertRaises(ConflictError):
            await self.service.handle_risk_result(event)

    async def test_concurrent_risk_results_only_one_wins(self) -> None:
        created = await self._create_purchase()
        approved = await self._risk_event(created.operation_id, "approved")
        rejected = await self._risk_event(created.operation_id, "rejected")
        rejected.event_id = "EVT_RISK_CONCURRENT_REJECTED"
        outcomes = await asyncio.gather(
            self.service.handle_risk_result(approved),
            self.service.handle_risk_result(rejected),
            return_exceptions=True,
        )
        self.assertEqual(
            sum(not isinstance(item, Exception) for item in outcomes),
            1,
        )
        self.assertEqual(
            sum(isinstance(item, ConflictError) for item in outcomes),
            1,
        )

    async def test_manual_review_can_be_completed(self) -> None:
        created = await self._create_purchase()
        manual = await self._risk_event(created.operation_id, "manual_review")
        waiting = await self.service.handle_risk_result(manual)
        self.assertEqual(waiting.status, OperationStatus.MANUAL_REVIEW)
        record = await self.repository.get(created.operation_id)
        assert record is not None
        completed = await self.service.handle_manual_review_result(
            AgentEvent(
                event_id="EVT_MANUAL_APPROVED",
                event_type="risk.manual_review.completed",
                source_agent=AgentId.RISK,
                target_agents=[AgentId.OPERATOR],
                operation_id=created.operation_id,
                payload={
                    "operation_version": record.version,
                    "request_event_id": record.risk_request_event_id,
                    "decision": "approved",
                    "warnings": ["人工复核已通过"],
                },
                occurred_at=utc_now(),
                expires_at=utc_now() + timedelta(minutes=5),
            )
        )
        self.assertEqual(
            completed.status,
            OperationStatus.PENDING_CONFIRMATION,
        )

    async def test_confirmation_is_expired_proactively(self) -> None:
        created = await self._create_purchase()
        pending = await self.service.handle_risk_result(
            await self._risk_event(created.operation_id, "approved")
        )
        self.assertEqual(
            pending.status,
            OperationStatus.PENDING_CONFIRMATION,
        )
        record = await self.repository.get(created.operation_id)
        assert record is not None
        record.confirmation_expires_at = utc_now() - timedelta(seconds=1)
        await self.repository.save(record)
        self.assertEqual(await self.service.expire_confirmations(), 1)
        expired = await self.repository.get(created.operation_id)
        assert expired is not None
        self.assertEqual(expired.status, OperationStatus.EXPIRED)

    async def test_risk_result_requires_expiry(self) -> None:
        created = await self._create_purchase()
        event = await self._risk_event(created.operation_id, "approved")
        event.expires_at = None
        with self.assertRaises(ConflictError):
            await self.service.handle_risk_result(event)

    async def test_missing_fields_do_not_request_risk(self) -> None:
        response = await self.service.create_operation(
            ChatOperationRequest(
                request_id="REQ_MISSING",
                session_id="S001",
                message="申购",
            ),
            self.operator,
            OperationIntent.PURCHASE,
            {},
            AgentId.CUSTOMER,
        )
        self.assertEqual(
            response.status,
            OperationStatus.NEED_MORE_INFORMATION,
        )
        self.assertIn("product_id", response.missing_fields)
        self.assertFalse(
            any(channel == EventChannel.RISK_COMMAND for channel, _ in self.publisher.events)
        )

    async def test_all_eight_intents_create_risk_review(self) -> None:
        cases = {
            OperationIntent.PURCHASE: {
                "customer_id": "C001",
                "product_id": "P001",
                "account_id": "A001",
                "amount": "100.00",
                "currency": "CNY",
            },
            OperationIntent.REDEEM: {
                "customer_id": "C001",
                "holding_id": "H001",
                "redeem_type": "all",
            },
            OperationIntent.TRANSFER: {
                "customer_id": "C001",
                "from_account_id": "A001",
                "to_account_id": "A002",
                "amount": "100.00",
                "currency": "CNY",
            },
            OperationIntent.RISK_REASSESSMENT: {
                "customer_id": "C001",
                "questionnaire_version": "v1",
                "answers": {"q1": "a"},
            },
            OperationIntent.UPDATE_PROFILE: {
                "customer_id": "C001",
                "field_name": "phone",
                "new_value": "13800138000",
            },
            OperationIntent.PRODUCT_QUERY: {
                "product_id": "P001",
                "fields": ["name"],
            },
            OperationIntent.SUSPICIOUS_REPORT: {
                "customer_id": "C001",
                "transaction_id": "TX001",
                "reason": "异常交易",
                "evidence_refs": [],
            },
            OperationIntent.CREATE_WORK_ORDER: {
                "customer_id": "C001",
                "work_order_type": "complaint",
                "description": "创建投诉工单",
                "priority": "medium",
            },
        }
        system_operator = OperatorContext(
            operator_id="SYSTEM",
            role="system",
            organization_id="ORG001",
        )
        for index, (intent, params) in enumerate(cases.items()):
            with self.subTest(intent=intent):
                response = await self.service.create_operation(
                    ChatOperationRequest(
                        request_id=f"REQ_ALL_{index}",
                        session_id="S001",
                        customer_id=params.get("customer_id"),
                        message=intent.value,
                    ),
                    system_operator,
                    intent,
                    params,
                    AgentId.CUSTOMER,
                )
                self.assertEqual(
                    response.status,
                    OperationStatus.WAITING_RISK_REVIEW,
                )

    async def test_operation_request_event_enters_same_flow(self) -> None:
        event = AgentEvent(
            event_id="EVT_COMMAND_001",
            event_type="operation.requested",
            source_agent=AgentId.ADVISOR,
            target_agents=[AgentId.OPERATOR],
            session_id="S001",
            operator_id="EMP001",
            customer_id="C001",
            intent=OperationIntent.PURCHASE,
            payload={
                "auth_token": encode_hs256_jwt(
                    {
                        "sub": "EMP001",
                        "role": "advisor",
                        "organization_id": "ORG001",
                        "customer_ids": ["C001"],
                        "account_ids": ["A001"],
                        "holding_ids": ["H001"],
                        "iss": "wealthsense",
                        "exp": int(time.time()) + 3600,
                    },
                    "development-jwt-secret-change-me",
                ),
                "params": {
                    "customer_id": "C001",
                    "product_id": "P001",
                    "account_id": "A001",
                    "amount": "100000.00",
                    "currency": "CNY",
                },
            },
            occurred_at=utc_now(),
        )
        response = await self.service.create_from_event(event)
        self.assertEqual(response.status, OperationStatus.WAITING_RISK_REVIEW)
        self.assertTrue(
            await self.repository.is_event_processed(event.event_id)
        )

    async def test_parameter_change_invalidates_old_risk_review(self) -> None:
        response = await self.service.create_operation(
            ChatOperationRequest(
                request_id="REQ_UPDATE_1",
                session_id="S001",
                customer_id="C001",
                message="申购",
            ),
            self.operator,
            OperationIntent.PURCHASE,
            {"customer_id": "C001"},
            AgentId.ADVISOR,
        )
        self.assertEqual(
            response.status,
            OperationStatus.NEED_MORE_INFORMATION,
        )
        updated = await self.service.update_parameters(
            response.operation_id,
            UpdateOperationRequest(
                request_id="REQ_UPDATE_2",
                updated_by="EMP001",
                params={
                    "product_id": "P001",
                    "account_id": "A001",
                    "amount": "100000.00",
                    "currency": "CNY",
                },
            ),
            self.operator,
        )
        self.assertEqual(updated.version, 2)
        self.assertEqual(
            updated.status,
            OperationStatus.WAITING_RISK_REVIEW,
        )

    async def test_stale_version_cannot_cas_new_waiting_state(self) -> None:
        created = await self._create_purchase()
        stale = await self.repository.get(created.operation_id)
        assert stale is not None
        await self.service.update_parameters(
            created.operation_id,
            UpdateOperationRequest(
                request_id="REQ_VERSION_2",
                updated_by="EMP001",
                params={"amount": "200000.00"},
            ),
            self.operator,
        )
        changed = await self.repository.transition(
            stale,
            OperationStatus.WAITING_RISK_REVIEW,
            OperationStatus.RISK_APPROVED,
            expected_version=stale.version,
            expected_risk_request_id=stale.risk_request_event_id,
        )
        self.assertFalse(changed)
        current = await self.repository.get(created.operation_id)
        assert current is not None
        self.assertEqual(current.version, 2)
        self.assertEqual(
            current.status,
            OperationStatus.WAITING_RISK_REVIEW,
        )

    async def test_timeout_can_be_reconciled_without_reexecution(self) -> None:
        created = await self.service.create_operation(
            ChatOperationRequest(
                request_id="REQ_TIMEOUT",
                session_id="S001",
                customer_id="C001",
                message="查询产品",
            ),
            OperatorContext(
                operator_id="EMP001",
                role="advisor",
                organization_id="ORG001",
                allowed_customer_ids={"C001"},
                allowed_account_ids={"A001"},
                allowed_holding_ids={"H001"},
            ),
            OperationIntent.PRODUCT_QUERY,
            {
                "product_id": "P001",
                "fields": ["name"],
                "simulate_timeout": True,
            },
            AgentId.ADVISOR,
        )
        # Extra Mock controls are intentionally ignored by strict operation schemas,
        # so inject the timeout only into the stored execution parameters.
        record = await self.repository.get(created.operation_id)
        assert record is not None
        record.params["simulate_timeout"] = True
        await self.repository.save(record)
        pending = await self.service.handle_risk_result(
            await self._risk_event(created.operation_id, "approved")
        )
        self.assertEqual(
            pending.status,
            OperationStatus.PENDING_VERIFICATION,
        )
        reconciled = await self.service.reconcile(
            created.operation_id,
            "REQ_RECONCILE",
        )
        self.assertEqual(reconciled.status, OperationStatus.SUCCEEDED)

    async def test_crashed_risk_approved_state_is_resumed(self) -> None:
        created = await self._create_purchase()
        record = await self.repository.get(created.operation_id)
        assert record is not None
        record.status = OperationStatus.RISK_APPROVED
        await self.repository.save(record)
        self.repository.operations[
            created.operation_id
        ].updated_at = utc_now() - timedelta(seconds=10)
        self.assertEqual(await self.service.resume_ready_operations(), 1)
        resumed = await self.repository.get(created.operation_id)
        assert resumed is not None
        self.assertEqual(
            resumed.status,
            OperationStatus.PENDING_CONFIRMATION,
        )

    async def test_crashed_executing_state_reuses_idempotency_key(self) -> None:
        created = await self.service.create_operation(
            ChatOperationRequest(
                request_id="REQ_EXECUTING_CRASH",
                session_id="S001",
                message="查询产品",
            ),
            self.operator,
            OperationIntent.PRODUCT_QUERY,
            {"product_id": "P001", "fields": ["name"]},
            AgentId.ADVISOR,
        )
        record = await self.repository.get(created.operation_id)
        assert record is not None
        record.status = OperationStatus.RISK_APPROVED
        await self.repository.save(record)
        await self.service._transition(
            record,
            OperationStatus.EXECUTING,
            execution_attempt_values={
                "attempt_id": "ATT_CRASH",
                "operation_id": record.operation_id,
                "idempotency_key": f"{record.operation_id}:{record.version}",
                "tool_name": record.intent.value,
                "request_json": record.params,
                "response_json": None,
                "status": "executing",
                "started_at": utc_now(),
                "completed_at": None,
            },
        )
        self.assertEqual(len(self.repository.attempts), 1)
        self.assertEqual(
            await self.service.reconcile_pending_operations(),
            1,
        )
        recovered = await self.repository.get(created.operation_id)
        assert recovered is not None
        self.assertEqual(recovered.status, OperationStatus.SUCCEEDED)
        self.assertEqual(self.repository.attempts[0]["status"], "succeeded")

    async def test_stale_execution_lock_does_not_block_recovery(self) -> None:
        created = await self.service.create_operation(
            ChatOperationRequest(
                request_id="REQ_STALE_LOCK",
                session_id="S001",
                message="查询产品",
            ),
            self.operator,
            OperationIntent.PRODUCT_QUERY,
            {"product_id": "P001", "fields": ["name"]},
            AgentId.ADVISOR,
        )
        record = await self.repository.get(created.operation_id)
        assert record is not None
        record.status = OperationStatus.RISK_APPROVED
        await self.repository.save(record)
        await self.service.state_store.acquire_lock(
            f"operator:idempotency:{record.operation_id}:{record.version}",
            3600,
        )
        with self.assertRaises(ConflictError):
            await self.service._execute(record, "REQ_STALE_LOCK_EXECUTE")
        executing = await self.repository.get(created.operation_id)
        assert executing is not None
        self.assertEqual(executing.status, OperationStatus.EXECUTING)
        self.assertEqual(
            await self.service.reconcile_pending_operations(),
            1,
        )
        recovered = await self.repository.get(created.operation_id)
        assert recovered is not None
        self.assertEqual(recovered.status, OperationStatus.SUCCEEDED)
