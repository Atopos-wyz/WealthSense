from datetime import timedelta

from app.dao.mysql.operation_repository import OperationRepository
from app.dao.redis.event_publisher import EventPublisher
from app.event.channels import EventChannel
from app.models.schemas.common import AgentEvent, AgentId, utc_now
from app.models.schemas.internal import OperationRecord
from app.utils.ids import new_id


class RiskReviewService:
    def __init__(
        self,
        repository: OperationRepository,
        publisher: EventPublisher,
        ttl_seconds: int,
    ) -> None:
        self.repository = repository
        self.publisher = publisher
        self.ttl_seconds = ttl_seconds

    async def request_review(self, operation: OperationRecord) -> AgentEvent:
        now = utc_now()
        event = AgentEvent(
            event_id=new_id("EVT"),
            event_type="risk.check.requested",
            source_agent=AgentId.OPERATOR,
            target_agents=[AgentId.RISK],
            correlation_id=operation.operation_id,
            operation_id=operation.operation_id,
            task_id=operation.task_id,
            session_id=operation.session_id,
            operator_id=operation.operator_id,
            customer_id=operation.customer_id,
            intent=operation.intent,
            payload={
                "operation_version": operation.version,
                "params": operation.params,
                "reply_channel": EventChannel.OPERATOR_RISK_RESULT.value,
            },
            occurred_at=now,
            expires_at=now + timedelta(seconds=self.ttl_seconds),
        )
        operation.risk_request_event_id = event.event_id
        updated = await self.repository.prepare_risk_review(
            operation.operation_id,
            operation.version,
            event.event_id,
            review_values={
                "operation_id": operation.operation_id,
                "operation_version": operation.version,
                "request_event_id": event.event_id,
                "result_event_id": None,
                "status": "waiting",
                "decision": None,
                "risk_level": None,
                "rule_hits_json": [],
                "warnings_json": [],
                "reason": "",
                "requested_at": now,
                "responded_at": None,
                "expires_at": event.expires_at,
            },
            outbox_values={
                "event_id": event.event_id,
                "channel": EventChannel.RISK_COMMAND.value,
                "payload": event.model_dump(mode="json"),
            },
        )
        if not updated:
            raise RuntimeError("operation changed before risk review publication")
        await self.publisher.publish(EventChannel.RISK_COMMAND, event)
        return event
