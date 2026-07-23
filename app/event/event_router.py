import logging

from app.event.channels import EventChannel
from app.models.schemas.common import AgentEvent, AgentId
from app.models.schemas.operation import (
    CancelOperationRequest,
    ConfirmOperationRequest,
    UpdateOperationRequest,
)
from app.service.nl2api.operation_service import OperationService
from app.utils.exceptions import OperatorError

logger = logging.getLogger(__name__)


class OperatorEventRouter:
    def __init__(self, operation_service: OperationService) -> None:
        self.operation_service = operation_service

    async def handle(
        self,
        channel: EventChannel,
        event: AgentEvent,
    ) -> None:
        if AgentId.OPERATOR not in event.target_agents:
            return
        try:
            if event.event_type == "operation.requested":
                self._require_channel(channel, EventChannel.OPERATOR_COMMAND)
                await self.operation_service.create_from_event(event)
                return
            if event.event_type == "risk.check.completed":
                self._require_channel(
                    channel,
                    EventChannel.OPERATOR_RISK_RESULT,
                )
                await self.operation_service.handle_risk_result(event)
                return
            if event.event_type == "risk.manual_review.completed":
                self._require_channel(
                    channel,
                    EventChannel.OPERATOR_RISK_RESULT,
                )
                await self.operation_service.handle_manual_review_result(event)
                return
            if event.event_type == "operation.cancel.requested":
                self._require_channel(channel, EventChannel.OPERATOR_CONTROL)
                await self.operation_service.claim_control_event(event)
                if not event.operation_id:
                    raise ValueError("control event missing operation_id")
                operator = self.operation_service.operator_context_from_event(event)
                await self.operation_service.authorize_access(
                    event.operation_id,
                    operator,
                )
                await self.operation_service.cancel(
                    event.operation_id,
                    CancelOperationRequest(
                        request_id=event.event_id,
                        cancelled_by=operator.operator_id,
                        reason=str(event.payload.get("reason", "cancelled by event")),
                    ),
                )
                await self.operation_service.complete_control_event(
                    event.event_id
                )
                return
            if event.event_type == "operation.confirm.requested":
                self._require_channel(channel, EventChannel.OPERATOR_CONTROL)
                await self.operation_service.claim_control_event(event)
                if not event.operation_id:
                    raise ValueError("confirmation event missing operation_id")
                operator = self.operation_service.operator_context_from_event(event)
                await self.operation_service.authorize_access(
                    event.operation_id,
                    operator,
                )
                await self.operation_service.confirm(
                    event.operation_id,
                    ConfirmOperationRequest(
                        request_id=event.event_id,
                        confirmer_id=operator.operator_id,
                        operation_version=int(event.payload["operation_version"]),
                        params_hash=str(event.payload["params_hash"]),
                        confirmation_method=event.payload.get(
                            "confirmation_method",
                            "chat",
                        ),
                    ),
                )
                await self.operation_service.complete_control_event(
                    event.event_id
                )
                return
            if event.event_type == "operation.params.updated":
                self._require_channel(channel, EventChannel.OPERATOR_CONTROL)
                await self.operation_service.claim_control_event(event)
                if not event.operation_id:
                    raise ValueError("parameter event missing operation_id")
                operator = self.operation_service.operator_context_from_event(event)
                await self.operation_service.update_parameters(
                    event.operation_id,
                    UpdateOperationRequest(
                        request_id=event.event_id,
                        updated_by=operator.operator_id,
                        params=dict(event.payload.get("params", {})),
                    ),
                    operator,
                )
                await self.operation_service.complete_control_event(
                    event.event_id
                )
                return
            logger.warning("ignored unsupported event type: %s", event.event_type)
        except (ValueError, KeyError) as exc:
            logger.exception("operator event payload is invalid")
            await self.operation_service.publish_event_error(
                event,
                OperatorError(
                    "OP_EVENT_INVALID",
                    str(exc),
                ),
            )
        except OperatorError as exc:
            logger.warning(
                "operator event rejected: %s (%s)",
                exc.message,
                exc.code,
            )
            await self.operation_service.publish_event_error(event, exc)

    @staticmethod
    def _require_channel(
        actual: EventChannel,
        expected: EventChannel,
    ) -> None:
        if actual != expected:
            raise OperatorError(
                "OP_EVENT_CHANNEL_INVALID",
                f"事件必须发布到 {expected.value}",
            )
