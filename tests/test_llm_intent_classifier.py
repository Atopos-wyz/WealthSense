import asyncio
import json
import unittest
from unittest.mock import AsyncMock

import httpx
from pydantic import ValidationError

from app.agent.operator.agent import BusinessOperatorAgent
from app.agent.operator.llm_intent_classifier import (
    HybridIntentRecognizer,
    IntentRecognition,
    OpenAICompatibleIntentRecognizer,
)
from app.event.channels import EventChannel
from app.config.settings import Settings
from app.models.schemas.common import OperationIntent
from app.models.schemas.common import OperationStatus
from app.models.schemas.operation import (
    ChatOperationRequest,
    OperatorContext,
)
from tests.helpers import build_test_service


def _chat_completion(content: dict) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": json.dumps(content, ensure_ascii=False),
                    }
                }
            ]
        },
    )


class OpenAICompatibleIntentRecognizerTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_valid_structured_result(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/v1/chat/completions")
            self.assertEqual(request.headers["authorization"], "Bearer secret")
            request_body = json.loads(request.content)
            user_payload = json.loads(request_body["messages"][1]["content"])
            self.assertEqual(user_payload, {"message": "给这个产品配十万"})
            return _chat_completion(
                {
                    "intent": "purchase",
                    "confidence": 0.96,
                    "params": {"amount": 100000},
                }
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            recognizer = OpenAICompatibleIntentRecognizer(
                base_url="https://llm.example/v1",
                api_key="secret",
                model="test-model",
                timeout_seconds=1,
                client=client,
            )
            result = await recognizer.recognize(
                "给这个产品配十万",
                {"customer_id": "C_SECRET", "private_note": "sensitive"},
            )

        self.assertEqual(result.intent, OperationIntent.PURCHASE)
        self.assertEqual(result.params["amount"], 100000)
        self.assertEqual(result.source, "llm")

    async def test_low_confidence_uses_keyword_fallback(self) -> None:
        llm = AsyncMock()
        llm.recognize.return_value = IntentRecognition(
            intent=OperationIntent.PURCHASE,
            confidence=0.4,
            params={"amount": 100000},
        )
        recognizer = HybridIntentRecognizer(
            llm,
            confidence_threshold=0.75,
        )

        result = await recognizer.recognize("请查询产品详情", {})

        self.assertEqual(result.intent, OperationIntent.PRODUCT_QUERY)
        self.assertEqual(result.source, "keyword_fallback")
        self.assertEqual(
            result.fallback_reason,
            "confidence_below_threshold",
        )

    async def test_invalid_model_response_uses_keyword_fallback(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            del request
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "not-json"}}]},
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            llm = OpenAICompatibleIntentRecognizer(
                base_url="https://llm.example/v1",
                api_key="secret",
                model="test-model",
                timeout_seconds=1,
                client=client,
            )
            recognizer = HybridIntentRecognizer(
                llm,
                confidence_threshold=0.75,
            )
            result = await recognizer.recognize("转账6万元", {})

        self.assertEqual(result.intent, OperationIntent.TRANSFER)
        self.assertEqual(result.source, "keyword_fallback")
        self.assertTrue(result.fallback_reason.startswith("llm_error:"))

    async def test_missing_configuration_uses_keyword_fallback(self) -> None:
        recognizer = HybridIntentRecognizer(
            None,
            confidence_threshold=0.75,
        )

        result = await recognizer.recognize("创建一个投诉工单", {})

        self.assertEqual(result.intent, OperationIntent.CREATE_WORK_ORDER)
        self.assertEqual(result.fallback_reason, "llm_not_configured")

    async def test_transport_error_uses_keyword_fallback(self) -> None:
        llm = AsyncMock()
        llm.recognize.side_effect = httpx.ReadTimeout("timed out")
        recognizer = HybridIntentRecognizer(
            llm,
            confidence_threshold=0.75,
        )

        result = await recognizer.recognize("重新进行风险测评", {})

        self.assertEqual(result.intent, OperationIntent.RISK_REASSESSMENT)
        self.assertEqual(result.source, "keyword_fallback")
        self.assertEqual(result.fallback_reason, "llm_error:ReadTimeout")

    async def test_unexpected_model_error_uses_keyword_fallback(self) -> None:
        llm = AsyncMock()
        llm.recognize.side_effect = RuntimeError("provider bug")
        recognizer = HybridIntentRecognizer(
            llm,
            confidence_threshold=0.75,
        )

        result = await recognizer.recognize("申购十万元产品", {})

        self.assertEqual(result.intent, OperationIntent.PURCHASE)
        self.assertEqual(result.source, "keyword_fallback")
        self.assertEqual(result.fallback_reason, "llm_error:RuntimeError")

    async def test_cancellation_is_not_swallowed_by_fallback(self) -> None:
        llm = AsyncMock()
        llm.recognize.side_effect = asyncio.CancelledError
        recognizer = HybridIntentRecognizer(
            llm,
            confidence_threshold=0.75,
        )

        with self.assertRaises(asyncio.CancelledError):
            await recognizer.recognize("申购十万元产品", {})

    async def test_llm_unknown_allows_keyword_fallback(self) -> None:
        llm = AsyncMock()
        llm.recognize.return_value = IntentRecognition(
            intent=OperationIntent.UNKNOWN,
            confidence=0.99,
            params={},
        )
        recognizer = HybridIntentRecognizer(
            llm,
            confidence_threshold=0.75,
        )

        result = await recognizer.recognize("帮我赎回这个产品", {})

        self.assertEqual(result.intent, OperationIntent.REDEEM)
        self.assertEqual(result.fallback_reason, "llm_returned_unknown")


class BusinessOperatorAgentRecognitionTests(unittest.IsolatedAsyncioTestCase):
    async def test_parameter_priority_is_known_then_llm_then_regex(self) -> None:
        operation_service = AsyncMock()
        operation_service.create_operation.return_value = object()
        recognizer = AsyncMock()
        recognizer.recognize.return_value = IntentRecognition(
            intent=OperationIntent.PURCHASE,
            confidence=0.95,
            params={
                "customer_id": "C_FROM_LLM",
                "product_id": "P_FROM_LLM",
                "amount": 200000,
            },
        )
        agent = BusinessOperatorAgent(operation_service, recognizer)
        request = ChatOperationRequest(
            request_id="REQ_LLM_001",
            session_id="SESSION_001",
            message="为C001购买P001十万元产品",
            known_params={
                "customer_id": "C_TRUSTED",
                "amount": 300000,
            },
        )
        operator = OperatorContext(
            operator_id="EMP001",
            role="advisor",
        )

        await agent.handle_chat(request, operator)

        call = operation_service.create_operation.await_args
        submitted_params = call.kwargs["params"]
        self.assertEqual(submitted_params["customer_id"], "C_TRUSTED")
        self.assertEqual(submitted_params["amount"], 300000)
        self.assertEqual(submitted_params["product_id"], "P_FROM_LLM")

    async def test_request_customer_id_overrides_llm_customer(self) -> None:
        operation_service = AsyncMock()
        operation_service.create_operation.return_value = object()
        recognizer = AsyncMock()
        recognizer.recognize.return_value = IntentRecognition(
            intent=OperationIntent.PRODUCT_QUERY,
            confidence=0.99,
            params={
                "customer_id": "C_FROM_LLM",
                "product_id": "P001",
            },
        )
        agent = BusinessOperatorAgent(operation_service, recognizer)
        request = ChatOperationRequest(
            request_id="REQ_CUSTOMER_CONTEXT",
            session_id="SESSION_001",
            customer_id="C_TRUSTED_CONTEXT",
            message="查询产品详情",
        )

        await agent.handle_chat(
            request,
            OperatorContext(operator_id="EMP001", role="advisor"),
        )

        submitted_params = (
            operation_service.create_operation.await_args.kwargs["params"]
        )
        self.assertEqual(
            submitted_params["customer_id"],
            "C_TRUSTED_CONTEXT",
        )

    async def test_llm_params_still_use_strong_validation(self) -> None:
        service, _, publisher = build_test_service()
        recognizer = AsyncMock()
        recognizer.recognize.return_value = IntentRecognition(
            intent=OperationIntent.PURCHASE,
            confidence=0.99,
            params={
                "customer_id": "C001",
                "product_id": "P001",
                "account_id": "A001",
                "amount": -100,
            },
        )
        agent = BusinessOperatorAgent(service, recognizer)
        request = ChatOperationRequest(
            request_id="REQ_INVALID_LLM_PARAMS",
            session_id="SESSION_001",
            message="购买这个产品",
        )
        operator = OperatorContext(
            operator_id="EMP001",
            role="advisor",
            allowed_customer_ids={"C001"},
            allowed_account_ids={"A001"},
        )

        response = await agent.handle_chat(request, operator)

        self.assertEqual(response.status, OperationStatus.VALIDATION_FAILED)
        self.assertEqual(response.error.code, "OP_PARAM_INVALID")
        self.assertFalse(
            any(
                channel == EventChannel.RISK_COMMAND
                for channel, _ in publisher.events
            )
        )


class LlmSettingsTests(unittest.TestCase):
    def test_remote_llm_requires_https(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(
                _env_file=None,
                llm_base_url="http://llm.example/v1",
            )

    def test_loopback_llm_can_use_http(self) -> None:
        settings = Settings(
            _env_file=None,
            llm_base_url="http://127.0.0.1:11434/v1",
            llm_api_key="local",
            llm_model="local-model",
        )
        self.assertTrue(settings.has_llm_intent_recognition)
