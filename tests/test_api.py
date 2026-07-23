import unittest

from fastapi.testclient import TestClient

from app.main import app


class ApiTests(unittest.TestCase):
    def test_health_and_create_operation(self) -> None:
        with TestClient(app) as client:
            self.assertEqual(client.get("/health").status_code, 200)
            response = client.post(
                "/api/operation/chat",
                headers={
                    "X-Operator-Id": "EMP001",
                    "X-Operator-Role": "advisor",
                    "X-Organization-Id": "ORG001",
                },
                json={
                    "request_id": "REQ_API_001",
                    "session_id": "S001",
                    "customer_id": "C001",
                    "message": "申购10万元稳健增利A",
                    "known_params": {
                        "product_id": "P001",
                        "account_id": "A001"
                    }
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertEqual(body["status"], "waiting_risk_review")

