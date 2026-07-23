import unittest
import time

from fastapi.testclient import TestClient

from app.main import app
from app.utils.security import encode_hs256_jwt


class ApiTests(unittest.TestCase):
    def test_operation_requires_jwt(self) -> None:
        with TestClient(app) as client:
            response = client.post(
                "/api/operation/chat",
                json={
                    "request_id": "REQ_NO_AUTH",
                    "session_id": "S001",
                    "message": "查询产品",
                    "known_params": {"product_id": "P001"},
                },
            )
            self.assertEqual(response.status_code, 403)
            self.assertEqual(
                response.json()["error"]["code"],
                "OP_AUTH_REQUIRED",
            )

    def test_health_and_create_operation(self) -> None:
        with TestClient(app) as client:
            self.assertEqual(client.get("/health").status_code, 200)
            token = encode_hs256_jwt(
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
            )
            response = client.post(
                "/api/operation/chat",
                headers={"Authorization": f"Bearer {token}"},
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
