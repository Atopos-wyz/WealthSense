import logging

from app.agent.operator.entity_resolver import resolve_entities
from app.agent.operator.llm_intent_classifier import (
    HybridIntentRecognizer,
    IntentRecognizer,
)
from app.agent.operator.parameter_extractor import extract_parameters
from app.models.schemas.common import AgentId
from app.models.schemas.operation import (
    ChatOperationRequest,
    OperationResponse,
    OperatorContext,
)
from app.service.nl2api.operation_service import OperationService

logger = logging.getLogger(__name__)


class BusinessOperatorAgent:
    def __init__(
        self,
        operation_service: OperationService,
        intent_recognizer: IntentRecognizer | None = None,
    ) -> None:
        self.operation_service = operation_service
        self.intent_recognizer = intent_recognizer or HybridIntentRecognizer(
            None,
            confidence_threshold=0.75,
        )

    async def handle_chat(
        self,
        request: ChatOperationRequest,
        operator: OperatorContext,
    ) -> OperationResponse:
        recognition = await self.intent_recognizer.recognize(
            request.message,
            request.known_params,
        )
        rule_params = extract_parameters(
            request.message,
            recognition.intent,
            {},
        )
        params = {
            **rule_params,
            **recognition.params,
            **request.known_params,
        }
        params = resolve_entities(request.message, params)
        if request.customer_id:
            params["customer_id"] = request.customer_id
        logger.info(
            "operator intent recognized",
            extra={
                "intent": recognition.intent.value,
                "classification_source": recognition.source,
                "confidence": recognition.confidence,
                "fallback_reason": recognition.fallback_reason,
                "latency_ms": recognition.latency_ms,
            },
        )
        return await self.operation_service.create_operation(
            request=request,
            operator=operator,
            intent=recognition.intent,
            params=params,
            source_agent=AgentId.CUSTOMER,
        )

