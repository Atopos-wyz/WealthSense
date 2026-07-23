"""FastAPI 路由与统一响应契约测试。"""

import unittest

from fastapi.testclient import TestClient

from app.api.risk.router import get_risk_service
from app.main import app


class ApiContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_health_uses_unified_response(self) -> None:
        response = self.client.get("/health", headers={"X-Trace-ID": "test-trace"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["code"], 200)
        self.assertEqual(body["message"], "success")
        self.assertEqual(body["data"], {"status": "UP"})
        self.assertEqual(body["trace_id"], "test-trace")
        self.assertEqual(response.headers["X-Trace-ID"], "test-trace")

    def test_questionnaire_endpoint_returns_mock_questions(self) -> None:
        response = self.client.get("/api/risk/questionnaire")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["data"]["total_questions"], 16)
        self.assertEqual(len(body["data"]["questions"]), 16)
        self.assertTrue(
            all(
                len(question["options"]) == 4
                for question in body["data"]["questions"]
            )
        )

    def test_invalid_assessment_request_uses_unified_error(self) -> None:
        app.dependency_overrides[get_risk_service] = lambda: object()
        try:
            response = self.client.post(
                "/api/risk/assessment",
                json={"customer_id": 0, "answers": []},
            )
        finally:
            app.dependency_overrides.pop(get_risk_service, None)

        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["code"], 400)
        self.assertEqual(body["message"], "请求参数错误")
        self.assertIsInstance(body["data"]["details"], list)
        self.assertTrue(body["trace_id"])
