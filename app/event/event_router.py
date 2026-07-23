import logging

from app.models.schemas.common import AgentEvent, AgentId
from app.models.schemas.operation import CancelOperationRequest
from app.service.nl2api.operation_service import OperationService
from app.utils.exceptions import OperatorError

logger = logging.getLogger(__name__)


class OperatorEventRouter:
    def __init__(self, operation_service: OperationService) -> None:
        self.operation_service = operation_service

    async def handle(self, event: AgentEvent) -> None:
        if AgentId.OPERATOR not in event.target_agents:
            return
        try:
            if event.event_type == "operation.requested":
                await self.operation_service.create_from_event(event)
                return
            if event.event_type == "risk.check.completed":
                await self.operation_service.handle_risk_result(event)
                return
            if event.event_type == "operation.cancel.requested":
                if not event.operation_id:
                    raise ValueError("control event missing operation_id")
                await self.operation_service.cancel(
                    event.operation_id,
                    CancelOperationRequest(
                        request_id=event.event_id,
                        cancelled_by=event.operator_id or event.source_agent.value,
                        reason=str(event.payload.get("reason", "cancelled by event")),
                    ),
                )
                return
            logger.warning("ignored unsupported event type: %s", event.event_type)
        except OperatorError:
            logger.exception("operator event rejected")

