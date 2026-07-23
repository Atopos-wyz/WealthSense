import unittest

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
)
from app.utils.exceptions import ConflictError
from tests.helpers import build_test_service


class OperationFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.service, self.repository, self.publisher = build_test_service()
        self.operator = OperatorContext(
            operator_id="EMP001",
            role="advisor",
            organization_id="ORG001",
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
        return AgentEvent(
            event_id=f"EVT_RISK_{decision}",
            event_type="risk.check.completed",
            source_agent=AgentId.RISK,
            target_agents=[AgentId.OPERATOR],
            correlation_id=operation_id,
            operation_id=operation_id,
            payload={
                "operation_version": 1,
                "decision": decision,
                "risk_level": "low" if decision == "approved" else "high",
                "rule_hits": [],
                "warnings": [],
                "reason": "test",
            },
            occurred_at=utc_now(),
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

    async def test_duplicate_risk_event_is_rejected(self) -> None:
        created = await self._create_purchase()
        event = await self._risk_event(created.operation_id, "approved")
        await self.service.handle_risk_result(event)
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
                "operator_role": "advisor",
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
