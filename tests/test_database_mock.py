import unittest
from decimal import Decimal

from app.dao.mysql.mock_business_repository import (
    MockBusinessError,
    MockBusinessPending,
    _money,
    _numeric_candidate,
    _shares,
)
from app.models.entities import Base
from app.models.schemas.common import OperationIntent
from app.tool.operation.database_registry import DatabaseOperationToolRegistry
from app.tool.operation.registry import MockOperationError, MockOperationTimeout


class _FakeMockBusinessRepository:
    def __init__(self) -> None:
        self.result = {
            "operation_id": "OP001",
            "status": "succeeded",
        }
        self.error: Exception | None = None
        self.calls: list[tuple] = []

    async def execute(self, intent, operation_id, params, idempotency_key):
        self.calls.append((intent, operation_id, params, idempotency_key))
        if self.error:
            raise self.error
        return dict(self.result)

    async def get_status(self, operation_id):
        if self.error:
            raise self.error
        return dict(self.result) if operation_id == "OP001" else None

    async def seed_defaults(self, organization_id="ORG001", limit=3):
        return {"accounts_created": limit, "product_details_created": limit}


class DatabaseMockEntityTests(unittest.TestCase):
    def test_only_operator_prefixed_mock_tables_are_added(self) -> None:
        tables = {
            name
            for name in Base.metadata.tables
            if "mock" in name
        }
        self.assertEqual(
            tables,
            {
                "operator_mock_accounts",
                "operator_mock_holding_changes",
                "operator_mock_transactions",
                "operator_mock_product_details",
                "operator_mock_profile_updates",
                "operator_mock_risk_assessments",
                "operator_mock_suspicious_reports",
                "operator_mock_work_orders",
                "operator_mock_api_executions",
            },
        )
        for table_name in tables:
            self.assertTrue(table_name.startswith("operator_mock_"))

    def test_mock_tables_have_no_foreign_keys_to_shared_tables(self) -> None:
        for table in Base.metadata.tables.values():
            if table.name.startswith("operator_mock_"):
                self.assertEqual(list(table.foreign_keys), [])

    def test_decimal_normalization_is_stable(self) -> None:
        self.assertEqual(_money("10.005"), Decimal("10.01"))
        self.assertEqual(_shares("1.1234569"), Decimal("1.123456"))

    def test_external_ids_resolve_numeric_candidates(self) -> None:
        self.assertEqual(_numeric_candidate("C001", "C"), 1)
        self.assertEqual(_numeric_candidate("P-42", "P"), 42)
        self.assertIsNone(_numeric_candidate("CUSTOMER_X", "C"))


class DatabaseRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.repository = _FakeMockBusinessRepository()
        self.registry = DatabaseOperationToolRegistry(self.repository)

    async def test_delegates_without_changing_contract(self) -> None:
        result = await self.registry.execute(
            OperationIntent.PRODUCT_QUERY,
            "OP001",
            {"product_id": "P001"},
            "OP001:1",
        )
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(self.repository.calls[0][1], "OP001")

    async def test_committed_timeout_can_be_reconciled(self) -> None:
        with self.assertRaises(MockOperationTimeout):
            await self.registry.execute(
                OperationIntent.PRODUCT_QUERY,
                "OP001",
                {"product_id": "P001", "simulate_timeout": True},
                "OP001:1",
            )
        result = await self.registry.get_status("OP001")
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "succeeded")

    async def test_pending_execution_maps_to_timeout(self) -> None:
        self.repository.error = MockBusinessPending("still executing")
        with self.assertRaises(MockOperationTimeout):
            await self.registry.execute(
                OperationIntent.PRODUCT_QUERY,
                "OP001",
                {"product_id": "P001"},
                "OP001:1",
            )

    async def test_business_error_preserves_code(self) -> None:
        self.repository.error = MockBusinessError(
            "OP_ACCOUNT_FROZEN",
            "账户不可用",
        )
        with self.assertRaises(MockOperationError) as captured:
            await self.registry.execute(
                OperationIntent.TRANSFER,
                "OP001",
                {},
                "OP001:1",
            )
        self.assertEqual(captured.exception.code, "OP_ACCOUNT_FROZEN")


if __name__ == "__main__":
    unittest.main()
