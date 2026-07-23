from datetime import timedelta
from typing import Any

from app.dao.mysql.operation_repository import OperationRepository
from app.dao.redis.event_publisher import EventPublisher
from app.dao.redis.state_store import StateStore
from app.event.channels import EventChannel
from app.models.schemas.common import (
    AgentEvent,
    AgentId,
    ErrorDetail,
    OperationIntent,
    OperationStatus,
    RiskDecision,
    utc_now,
)
from app.models.schemas.internal import OperationRecord
from app.models.schemas.operation import (
    CancelOperationRequest,
    ChatOperationRequest,
    ConfirmOperationRequest,
    OperationResponse,
    OperatorContext,
    RiskReviewResult,
)
from app.service.nl2api.confirmation_service import (
    confirmation_values,
    requires_confirmation,
    validate_confirmation,
)
from app.service.nl2api.idempotency_service import IdempotencyService
from app.service.nl2api.permission_service import check_permission
from app.service.nl2api.risk_review_service import RiskReviewService
from app.service.nl2api.state_machine import assert_transition
from app.service.nl2api.validation_service import (
    hash_params,
    validate_operation_params,
)
from app.tool.operation.registry import (
    MockOperationError,
    MockOperationTimeout,
    OperationToolRegistry,
)
from app.utils.exceptions import ConflictError, NotFoundError, OperatorError
from app.utils.ids import new_id


class OperationService:
    def __init__(
        self,
        repository: OperationRepository,
        state_store: StateStore,
        publisher: EventPublisher,
        tool_registry: OperationToolRegistry,
        *,
        risk_review_ttl_seconds: int = 300,
        confirmation_ttl_seconds: int = 900,
        idempotency_ttl_seconds: int = 3600,
    ) -> None:
        self.repository = repository
        self.state_store = state_store
        self.publisher = publisher
        self.tool_registry = tool_registry
        self.confirmation_ttl_seconds = confirmation_ttl_seconds
        self.risk_review_service = RiskReviewService(
            repository,
            publisher,
            risk_review_ttl_seconds,
        )
        self.idempotency_service = IdempotencyService(
            state_store,
            idempotency_ttl_seconds,
        )

    async def create_operation(
        self,
        request: ChatOperationRequest,
        operator: OperatorContext,
        intent: OperationIntent,
        params: dict[str, Any],
        source_agent: AgentId,
        request_event_id: str | None = None,
    ) -> OperationResponse:
        record = OperationRecord(
            operation_id=new_id("OP"),
            request_id=request.request_id,
            request_event_id=request_event_id,
            source_agent=source_agent,
            task_id=request.task_id,
            session_id=request.session_id,
            operator_id=operator.operator_id,
            operator_role=operator.role,
            organization_id=operator.organization_id,
            customer_id=request.customer_id or params.get("customer_id"),
            intent=intent,
            status=OperationStatus.DRAFT,
            params=params,
        )
        await self.repository.create(record)
        await self._audit(record, "operation.created", None, record.status)
        await self._transition(record, OperationStatus.RESOLVING_ENTITIES)

        try:
            normalized, missing_fields = validate_operation_params(intent, params)
        except OperatorError as exc:
            record.error_code = exc.code
            await self._transition(record, OperationStatus.VALIDATION_FAILED)
            return self._response(record, request.request_id, error=exc)

        if missing_fields:
            record.missing_fields = missing_fields
            await self._transition(record, OperationStatus.NEED_MORE_INFORMATION)
            return self._response(record, request.request_id)

        record.params = normalized
        record.customer_id = normalized.get("customer_id", record.customer_id)
        record.params_hash = hash_params(normalized)
        record.confirmation_required = requires_confirmation(intent, normalized)
        await self.repository.add_version(record, operator.operator_id)
        await self._transition(record, OperationStatus.VALIDATING)

        try:
            check_permission(operator, intent, record.customer_id)
        except OperatorError as exc:
            record.error_code = exc.code
            await self._transition(record, OperationStatus.PERMISSION_DENIED)
            return self._response(record, request.request_id, error=exc)

        await self._transition(record, OperationStatus.WAITING_RISK_REVIEW)
        await self.risk_review_service.request_review(record)
        return self._response(record, request.request_id)

    async def create_from_event(self, event: AgentEvent) -> OperationResponse:
        if await self.repository.is_event_processed(event.event_id):
            raise ConflictError(
                "OP_EVENT_DUPLICATE",
                "事件已经处理",
            )
        if event.expires_at and event.expires_at <= utc_now():
            raise OperatorError("OP_EVENT_EXPIRED", "事件已经过期")
        payload = dict(event.payload)
        params = dict(payload.pop("params", payload))
        operator = OperatorContext(
            operator_id=event.operator_id or str(payload.pop("operator_id", "SYSTEM")),
            role=str(payload.pop("operator_role", "system")),
            organization_id=str(payload.pop("organization_id", "ORG001")),
        )
        request = ChatOperationRequest(
            request_id=event.event_id,
            session_id=event.session_id or new_id("S"),
            task_id=event.task_id,
            customer_id=event.customer_id,
            message=str(payload.pop("message", event.intent.value if event.intent else "")),
            known_params=params,
        )
        intent = event.intent or OperationIntent.UNKNOWN
        response = await self.create_operation(
            request,
            operator,
            intent,
            params,
            event.source_agent,
            event.event_id,
        )
        await self.repository.mark_event_processed(
            event.event_id,
            event.event_type,
            event.source_agent.value,
        )
        return response

    async def handle_risk_result(self, event: AgentEvent) -> OperationResponse:
        if event.source_agent != AgentId.RISK:
            raise OperatorError(
                "OP_SOURCE_UNTRUSTED",
                "风控结果必须来自risk Agent",
            )
        if await self.repository.is_event_processed(event.event_id):
            raise ConflictError("OP_EVENT_DUPLICATE", "风控结果事件已经处理")
        operation_id = event.operation_id or event.correlation_id
        if not operation_id:
            raise OperatorError("OP_RISK_RESULT_INVALID", "缺少operation_id")
        record = await self._require(operation_id)
        if record.status != OperationStatus.WAITING_RISK_REVIEW:
            raise ConflictError(
                "OP_RISK_RESULT_INVALID",
                "操作当前不等待风控结果",
            )

        risk_result = RiskReviewResult(
            event_id=event.event_id,
            operation_id=operation_id,
            operation_version=int(event.payload.get("operation_version", 0)),
            decision=RiskDecision(event.payload["decision"]),
            risk_level=event.payload.get("risk_level"),
            rule_hits=event.payload.get("rule_hits", []),
            warnings=event.payload.get("warnings", []),
            reason=event.payload.get("reason", ""),
            occurred_at=event.occurred_at,
            expires_at=event.expires_at,
        )
        if risk_result.operation_version != record.version:
            raise ConflictError(
                "OP_RISK_RESULT_INVALID",
                "风控结果与当前操作版本不匹配",
            )
        if risk_result.expires_at and risk_result.expires_at <= utc_now():
            raise ConflictError("OP_RISK_RESULT_INVALID", "风控结果已经过期")

        record.risk_result = risk_result.model_dump(mode="json")
        record.warnings.extend(risk_result.warnings)
        await self.repository.update_risk_review(
            record.risk_request_event_id or "",
            {
                "result_event_id": event.event_id,
                "status": "completed",
                "decision": risk_result.decision.value,
                "risk_level": risk_result.risk_level,
                "rule_hits_json": risk_result.rule_hits,
                "warnings_json": risk_result.warnings,
                "reason": risk_result.reason,
                "responded_at": utc_now(),
            },
        )
        await self.repository.mark_event_processed(
            event.event_id,
            event.event_type,
            event.source_agent.value,
        )

        if risk_result.decision == RiskDecision.REJECTED:
            record.error_code = "OP_RISK_REJECTED"
            await self._transition(record, OperationStatus.RISK_REJECTED)
            await self._publish_result(record)
            return self._response(record, event.event_id)
        if risk_result.decision == RiskDecision.MANUAL_REVIEW:
            await self._transition(record, OperationStatus.MANUAL_REVIEW)
            await self._publish_result(record)
            return self._response(record, event.event_id)

        await self._transition(record, OperationStatus.RISK_APPROVED)
        if record.confirmation_required:
            await self._transition(record, OperationStatus.PENDING_CONFIRMATION)
            expires_at = utc_now() + timedelta(
                seconds=self.confirmation_ttl_seconds
            )
            await self.state_store.put(
                f"operator:confirmation:{record.operation_id}",
                {
                    "operation_id": record.operation_id,
                    "version": record.version,
                    "params_hash": record.params_hash,
                    "expires_at": expires_at.isoformat(),
                },
                self.confirmation_ttl_seconds,
            )
            await self._publish_status(record, "operation.pending_confirmation")
            return self._response(
                record,
                event.event_id,
                confirmation_expires_at=expires_at,
            )
        return await self._execute(record, event.event_id)

    async def confirm(
        self,
        operation_id: str,
        request: ConfirmOperationRequest,
    ) -> OperationResponse:
        record = await self._require(operation_id)
        if record.status != OperationStatus.PENDING_CONFIRMATION:
            raise ConflictError(
                "OP_CONFIRMATION_REQUIRED",
                "操作当前不可确认",
            )
        pending = await self.state_store.get(
            f"operator:confirmation:{operation_id}"
        )
        if not pending:
            await self._transition(record, OperationStatus.EXPIRED)
            raise ConflictError(
                "OP_CONFIRMATION_EXPIRED",
                "确认请求已经过期",
            )
        validate_confirmation(record, request)
        await self.repository.add_confirmation(
            confirmation_values(
                record,
                request,
                self.confirmation_ttl_seconds,
            )
        )
        await self._transition(record, OperationStatus.CONFIRMED)
        await self.state_store.delete(f"operator:confirmation:{operation_id}")
        await self._publish_status(record, "operation.confirmed")
        return await self._execute(record, request.request_id)

    async def cancel(
        self,
        operation_id: str,
        request: CancelOperationRequest,
    ) -> OperationResponse:
        record = await self._require(operation_id)
        await self._transition(
            record,
            OperationStatus.CANCELLED,
            actor_id=request.cancelled_by,
            detail={"reason": request.reason},
        )
        await self.state_store.delete(f"operator:confirmation:{operation_id}")
        await self._publish_result(record)
        return self._response(record, request.request_id)

    async def get_response(
        self,
        operation_id: str,
        request_id: str,
    ) -> OperationResponse:
        return self._response(await self._require(operation_id), request_id)

    async def expire_risk_reviews(self) -> int:
        operation_ids = await self.repository.find_expired_risk_operations(
            utc_now()
        )
        expired_count = 0
        for operation_id in operation_ids:
            record = await self._require(operation_id)
            if record.status != OperationStatus.WAITING_RISK_REVIEW:
                continue
            record.error_code = "OP_RISK_REVIEW_TIMEOUT"
            await self._transition(
                record,
                OperationStatus.RISK_REVIEW_TIMEOUT,
            )
            if record.risk_request_event_id:
                await self.repository.update_risk_review(
                    record.risk_request_event_id,
                    {
                        "status": "timeout",
                        "responded_at": utc_now(),
                    },
                )
            await self._publish_result(record)
            expired_count += 1
        return expired_count

    async def _execute(
        self,
        record: OperationRecord,
        request_id: str,
    ) -> OperationResponse:
        await self.idempotency_service.acquire(record.operation_id, record.version)
        await self._transition(record, OperationStatus.EXECUTING)
        attempt_id = new_id("ATT")
        idempotency_key = f"{record.operation_id}:{record.version}"
        await self.repository.add_attempt(
            {
                "attempt_id": attempt_id,
                "operation_id": record.operation_id,
                "idempotency_key": idempotency_key,
                "tool_name": record.intent.value,
                "request_json": record.params,
                "response_json": None,
                "status": "executing",
                "started_at": utc_now(),
                "completed_at": None,
            }
        )
        try:
            result = await self.tool_registry.execute(
                record.intent,
                record.operation_id,
                record.params,
                idempotency_key,
            )
        except MockOperationTimeout:
            record.error_code = "OP_MOCK_API_TIMEOUT"
            await self._transition(record, OperationStatus.PENDING_VERIFICATION)
            await self.repository.update_attempt(
                attempt_id,
                {
                    "status": "pending_verification",
                    "completed_at": utc_now(),
                },
            )
            await self._publish_result(record)
            return self._response(record, request_id)
        except MockOperationError as exc:
            record.error_code = exc.code
            await self._transition(record, OperationStatus.FAILED)
            await self.repository.update_attempt(
                attempt_id,
                {
                    "status": "failed",
                    "response_json": {"code": exc.code, "message": exc.message},
                    "completed_at": utc_now(),
                },
            )
            await self._publish_result(record)
            return self._response(record, request_id)

        record.result = result
        record.completed_at = utc_now()
        await self._transition(record, OperationStatus.SUCCEEDED)
        await self.repository.update_attempt(
            attempt_id,
            {
                "status": "succeeded",
                "response_json": result,
                "completed_at": utc_now(),
            },
        )
        await self._publish_result(record)
        if "transaction_id" in result:
            await self._publish_transaction(record)
        return self._response(record, request_id)

    async def _transition(
        self,
        record: OperationRecord,
        target: OperationStatus,
        *,
        actor_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        old = record.status
        assert_transition(old, target)
        record.status = target
        await self.repository.save(record)
        await self._audit(
            record,
            f"operation.{target.value}",
            old,
            target,
            actor_id=actor_id,
            detail=detail,
        )

    async def _audit(
        self,
        record: OperationRecord,
        event_type: str,
        old_status: OperationStatus | None,
        new_status: OperationStatus | None,
        *,
        actor_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        await self.repository.add_audit(
            {
                "operation_id": record.operation_id,
                "event_type": event_type,
                "actor_type": "operator" if actor_id else "agent",
                "actor_id": actor_id or AgentId.OPERATOR.value,
                "old_status": old_status.value if old_status else None,
                "new_status": new_status.value if new_status else None,
                "detail_json": detail or {},
                "trace_id": record.request_id,
                "created_at": utc_now(),
            }
        )

    async def _publish_status(
        self,
        record: OperationRecord,
        event_type: str,
    ) -> None:
        event = self._result_event(record, event_type)
        await self.publisher.publish(EventChannel.AGENT_RESULT, event)

    async def _publish_result(self, record: OperationRecord) -> None:
        event = self._result_event(
            record,
            f"operation.{record.status.value}",
        )
        await self.publisher.publish(EventChannel.AGENT_RESULT, event)

    async def _publish_transaction(self, record: OperationRecord) -> None:
        event = AgentEvent(
            event_id=new_id("EVT"),
            event_type="transaction.created",
            source_agent=AgentId.OPERATOR,
            target_agents=[AgentId.RISK],
            correlation_id=record.operation_id,
            operation_id=record.operation_id,
            task_id=record.task_id,
            session_id=record.session_id,
            customer_id=record.customer_id,
            intent=record.intent,
            payload=record.result or {},
        )
        await self.publisher.publish(EventChannel.TRANSACTION_EVENT, event)

    def _result_event(
        self,
        record: OperationRecord,
        event_type: str,
    ) -> AgentEvent:
        targets = [record.source_agent]
        if AgentId.RISK not in targets:
            targets.append(AgentId.RISK)
        return AgentEvent(
            event_id=new_id("EVT"),
            event_type=event_type,
            source_agent=AgentId.OPERATOR,
            target_agents=targets,
            correlation_id=record.operation_id,
            operation_id=record.operation_id,
            task_id=record.task_id,
            session_id=record.session_id,
            customer_id=record.customer_id,
            intent=record.intent,
            payload={
                "status": record.status.value,
                "result": record.result,
                "error_code": record.error_code,
                "warnings": record.warnings,
            },
        )

    async def _require(self, operation_id: str) -> OperationRecord:
        record = await self.repository.get(operation_id)
        if not record:
            raise NotFoundError(
                "OP_NOT_FOUND",
                "操作不存在",
                details={"operation_id": operation_id},
            )
        return record

    def _response(
        self,
        record: OperationRecord,
        request_id: str,
        *,
        error: OperatorError | None = None,
        confirmation_expires_at=None,
    ) -> OperationResponse:
        reply_map = {
            OperationStatus.NEED_MORE_INFORMATION: "请补充缺失的业务参数。",
            OperationStatus.WAITING_RISK_REVIEW: "操作已创建，正在等待风控审核。",
            OperationStatus.RISK_REJECTED: "风控审核未通过，操作已终止。",
            OperationStatus.MANUAL_REVIEW: "操作需要人工审核。",
            OperationStatus.PENDING_CONFIRMATION: "风控已通过，请确认操作参数。",
            OperationStatus.SUCCEEDED: "操作执行成功。",
            OperationStatus.FAILED: "操作执行失败。",
            OperationStatus.PENDING_VERIFICATION: "请求已受理，最终状态正在确认。",
            OperationStatus.CANCELLED: "操作已取消。",
            OperationStatus.PERMISSION_DENIED: "当前用户无权执行该操作。",
            OperationStatus.VALIDATION_FAILED: "业务参数校验失败。",
        }
        error_detail = None
        if error:
            error_detail = ErrorDetail(
                code=error.code,
                message=error.message,
                retryable=error.retryable,
                details=error.details,
            )
        elif record.error_code:
            error_detail = ErrorDetail(
                code=record.error_code,
                message=reply_map.get(record.status, "操作未完成"),
            )
        return OperationResponse(
            request_id=request_id,
            operation_id=record.operation_id,
            version=record.version,
            intent=record.intent,
            status=record.status,
            source_agent=record.source_agent,
            params=record.params,
            missing_fields=record.missing_fields,
            warnings=record.warnings,
            confirmation_required=record.confirmation_required,
            confirmation_expires_at=confirmation_expires_at,
            result=record.result,
            reply=reply_map.get(record.status, "操作处理中。"),
            error=error_detail,
        )
