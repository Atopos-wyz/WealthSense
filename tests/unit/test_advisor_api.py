"""投顾普通响应与 SSE 流式接口契约测试。"""

import unittest

from fastapi.testclient import TestClient

from app.api.chat.advisor import get_advisor_agent
from app.main import app
from app.models.schemas.advisor import (
    AdvisorChatResponse,
    AdvisorIntent,
)


class FakeAdvisorAgent:
    async def chat(self, payload) -> AdvisorChatResponse:
        return AdvisorChatResponse(
            reply="已完成资产配置建议。",
            session_id=payload.session_id,
            intent=AdvisorIntent.ASSET_ALLOCATION,
            reasoning=["读取画像", "匹配配置模型"],
        )


class AdvisorApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def setUp(self) -> None:
        app.dependency_overrides[get_advisor_agent] = FakeAdvisorAgent

    def tearDown(self) -> None:
        app.dependency_overrides.pop(get_advisor_agent, None)

    def test_advisor_endpoint_uses_documented_contract(self) -> None:
        response = self.client.post(
            "/api/chat/advisor",
            json={
                "session_id": "session-api",
                "message": "帮我做资产配置",
                "user_id": "user-1",
                "customer_id": 1,
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["code"], 200)
        self.assertEqual(body["data"]["session_id"], "session-api")
        self.assertEqual(
            body["data"]["intent"],
            "ASSET_ALLOCATION",
        )
        self.assertIn("reply", body["data"])
        self.assertIn("recommendations", body["data"])
        self.assertIn("reasoning", body["data"])

    def test_advisor_stream_returns_sse_events(self) -> None:
        response = self.client.post(
            "/api/chat/advisor/stream",
            json={
                "session_id": "session-stream",
                "message": "帮我做资产配置",
                "user_id": "user-1",
                "customer_id": 1,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response.headers["content-type"].startswith(
                "text/event-stream"
            )
        )
        self.assertIn("event: started", response.text)
        self.assertIn("event: intent", response.text)
        self.assertIn("event: message", response.text)
        self.assertIn("event: completed", response.text)
