from app.agent.operator.entity_resolver import resolve_entities
from app.agent.operator.intent_classifier import classify_intent
from app.agent.operator.parameter_extractor import extract_parameters
from app.models.schemas.common import AgentId
from app.models.schemas.operation import (
    ChatOperationRequest,
    OperationResponse,
    OperatorContext,
)
from app.service.nl2api.operation_service import OperationService


class BusinessOperatorAgent:
    def __init__(self, operation_service: OperationService) -> None:
        self.operation_service = operation_service

    async def handle_chat(
        self,
        request: ChatOperationRequest,
        operator: OperatorContext,
    ) -> OperationResponse:
        intent = classify_intent(request.message)
        params = extract_parameters(
            request.message,
            intent,
            request.known_params,
        )
        params = resolve_entities(request.message, params)
        if request.customer_id:
            params.setdefault("customer_id", request.customer_id)
        return await self.operation_service.create_operation(
            request=request,
            operator=operator,
            intent=intent,
            params=params,
            source_agent=AgentId.CUSTOMER,
        )

