from datetime import timedelta
from typing import Any

from sqlalchemy.exc import IntegrityError

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
    UpdateOperationRequest,
)
from app.service.nl2api.confirmation_service import (
    confirmation_values,
    requires_confirmation,
    validate_confirmation,
)
from app.service.nl2api.idempotency_service import IdempotencyService
from app.service.nl2api.permission_service import check_permission
from app.service.nl2api.risk_review_service import RiskReviewService
from app.service.nl2api.state_machine import InvalidStateTransition, assert_transition
from app.service.nl2api.validation_service import (
    hash_params,
    validate_operation_params,
)
from app.tool.operation.registry import (
    MockOperationError,
    MockOperationTimeout,
    OperationTool,
)
from app.utils.exceptions import (
    OperatorConflictError as ConflictError,
    OperatorError,
    OperatorNotFoundError as NotFoundError,
    OperatorPermissionDeniedError as PermissionDeniedError,
)
from app.utils.ids import new_id
from app.utils.security import decode_hs256_jwt


class OperationService:
    def __init__(
        self,
        repository: OperationRepository,
        state_store: StateStore,
        publisher: EventPublisher,
        tool_registry: OperationTool,
        *,
        risk_review_ttl_seconds: int = 300,
        confirmation_ttl_seconds: int = 900,
        idempotency_ttl_seconds: int = 3600,
        jwt_secret: str = "development-jwt-secret-change-me",
        jwt_issuer: str = "wealthsense",
    ) -> None:
        self.repository = repository
        self.state_store = state_store
        self.publisher = publisher
        self.tool_registry = tool_registry
        self.confirmation_ttl_seconds = confirmation_ttl_seconds
        self.jwt_secret = jwt_secret
        self.jwt_issuer = jwt_issuer
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
        existing = await self.repository.get_by_request(
            source_agent.value,
            operator.operator_id,
            operator.organization_id,
            request.request_id,
        )
        if existing:
            check_permission(
                operator,
                existing.intent,
                existing.customer_id,
                existing.params,
            )
            return self._response(existing, request.request_id)
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
            raw_message=request.message,
            params=params,
        )
        try:
            await self.repository.create(record)
        except (IntegrityError, ValueError):
            existing = await self.repository.get_by_request(
                source_agent.value,
                operator.operator_id,
                operator.organization_id,
                request.request_id,
            )
            if existing:
                check_permission(
                    operator,
                    existing.intent,
                    existing.customer_id,
                    existing.params,
                )
                return self._response(existing, request.request_id)
            raise
        await self._audit(record, "operation.created", None, record.status)
        await self._transition(record, OperationStatus.RESOLVING_ENTITIES)

        try:
            normalized, missing_fields = validate_operation_params(intent, params)
        except OperatorError as exc:
            record.error_code = exc.code
            await self._transition(record, OperationStatus.VALIDATION_FAILED)
            await self._publish_result(record)
            return self._response(record, request.request_id, error=exc)

        if missing_fields:
            record.missing_fields = missing_fields
            await self._transition(record, OperationStatus.NEED_MORE_INFORMATION)
            await self._publish_result(record)
            return self._response(record, request.request_id)

        record.params = normalized
        record.customer_id = normalized.get("customer_id", record.customer_id)
        record.params_hash = hash_params(normalized)
        record.confirmation_required = requires_confirmation(intent, normalized)
        await self.repository.add_version(record, operator.operator_id)
        await self._transition(record, OperationStatus.VALIDATING)

        try:
            check_permission(operator, intent, record.customer_id, record.params)
        except OperatorError as exc:
            record.error_code = exc.code
            await self._transition(record, OperationStatus.PERMISSION_DENIED)
            await self._publish_result(record)
            return self._response(record, request.request_id, error=exc)

        await self._transition(record, OperationStatus.WAITING_RISK_REVIEW)
        await self.risk_review_service.request_review(record)
        await self._publish_status(record, "operation.accepted")
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
        operator = self.operator_context_from_event(event)
        payload.pop("auth_token", None)
        params_payload = payload.pop("params", None)
        params = dict(params_payload if isinstance(params_payload, dict) else payload)
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

    def operator_context_from_event(
        self,
        event: AgentEvent,
    ) -> OperatorContext:
        role_by_source = {
            AgentId.CUSTOMER: "customer",
            AgentId.ADVISOR: "advisor",
            AgentId.RISK: "risk_officer",
            AgentId.ANALYST: "analyst",
        }
        role = role_by_source.get(event.source_agent)
        if not role:
            raise OperatorError(
                "OP_SOURCE_UNTRUSTED",
                "该来源Agent不能发起业务操作",
            )
        token = event.payload.get("auth_token")
        if not isinstance(token, str):
            raise PermissionDeniedError(
                "OP_AUTH_REQUIRED",
                "跨Agent操作事件缺少用户授权令牌",
            )
        claims = decode_hs256_jwt(
            token,
            self.jwt_secret,
            self.jwt_issuer,
        )
        if str(claims["role"]) != role:
            raise PermissionDeniedError(
                "OP_AUTH_INVALID",
                "授权身份与来源Agent不匹配",
            )
        if event.operator_id and str(claims["sub"]) != event.operator_id:
            raise PermissionDeniedError(
                "OP_AUTH_INVALID",
                "授权身份与事件操作者不匹配",
            )
        allowed_customer_ids = set(claims.get("customer_ids", []))
        if (
            event.customer_id
            and event.customer_id not in allowed_customer_ids
        ):
            raise PermissionDeniedError(
                "OP_CUSTOMER_OUT_OF_SCOPE",
                "事件客户不在授权范围内",
            )
        return OperatorContext(
            operator_id=str(claims["sub"]),
            role=role,
            organization_id=str(claims["organization_id"]),
            allowed_customer_ids=allowed_customer_ids,
            allowed_account_ids=set(claims.get("account_ids", [])),
            allowed_holding_ids=set(claims.get("holding_ids", [])),
        )

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
        request_event_id = event.payload.get("request_event_id")
        if request_event_id != record.risk_request_event_id:
            raise ConflictError(
                "OP_RISK_RESULT_INVALID",
                "风控结果未关联当前审核请求",
            )
        if not risk_result.expires_at:
            raise ConflictError(
                "OP_RISK_RESULT_INVALID",
                "风控结果缺少有效期",
            )
        if risk_result.expires_at <= utc_now():
            raise ConflictError("OP_RISK_RESULT_INVALID", "风控结果已经过期")

        record.risk_result = risk_result.model_dump(mode="json")
        record.warnings.extend(risk_result.warnings)
        if risk_result.decision == RiskDecision.REJECTED:
            record.error_code = "OP_RISK_REJECTED"
            risk_target = OperationStatus.RISK_REJECTED
        elif risk_result.decision == RiskDecision.MANUAL_REVIEW:
            risk_target = OperationStatus.MANUAL_REVIEW
        else:
            risk_target = OperationStatus.RISK_APPROVED
        await self._transition(
            record,
            risk_target,
            expected_risk_request_id=record.risk_request_event_id,
        )
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
            await self._publish_result(record)
            return self._response(record, event.event_id)
        if risk_result.decision == RiskDecision.MANUAL_REVIEW:
            await self._publish_result(record)
            return self._response(record, event.event_id)

        return await self._continue_risk_approved(record, event.event_id)

    async def handle_manual_review_result(
        self,
        event: AgentEvent,
    ) -> OperationResponse:
        if event.source_agent != AgentId.RISK:
            raise OperatorError(
                "OP_SOURCE_UNTRUSTED",
                "人工复核结果必须来自risk Agent",
            )
        if await self.repository.is_event_processed(event.event_id):
            raise ConflictError("OP_EVENT_DUPLICATE", "人工复核事件已经处理")
        operation_id = event.operation_id or event.correlation_id
        if not operation_id:
            raise OperatorError("OP_RISK_RESULT_INVALID", "缺少operation_id")
        record = await self._require(operation_id)
        if record.status != OperationStatus.MANUAL_REVIEW:
            raise ConflictError(
                "OP_RISK_RESULT_INVALID",
                "操作当前不等待人工复核",
            )
        if int(event.payload.get("operation_version", 0)) != record.version:
            raise ConflictError(
                "OP_RISK_RESULT_INVALID",
                "人工复核结果与当前操作版本不匹配",
            )
        if (
            event.payload.get("request_event_id")
            != record.risk_request_event_id
        ):
            raise ConflictError(
                "OP_RISK_RESULT_INVALID",
                "人工复核结果未关联当前审核请求",
            )
        if not event.expires_at or event.expires_at <= utc_now():
            raise ConflictError(
                "OP_RISK_RESULT_INVALID",
                "人工复核结果已过期或缺少有效期",
            )
        decision = RiskDecision(str(event.payload.get("decision")))
        if decision not in {
            RiskDecision.APPROVED,
            RiskDecision.APPROVED_WITH_WARNING,
            RiskDecision.REJECTED,
        }:
            raise ConflictError(
                "OP_RISK_RESULT_INVALID",
                "人工复核必须给出通过或拒绝结论",
            )
        if decision == RiskDecision.REJECTED:
            record.error_code = "OP_RISK_REJECTED"
            await self._transition(
                record,
                OperationStatus.RISK_REJECTED,
                expected_risk_request_id=record.risk_request_event_id,
            )
            await self.repository.mark_event_processed(
                event.event_id,
                event.event_type,
                event.source_agent.value,
            )
            await self._publish_result(record)
            return self._response(record, event.event_id)
        record.warnings.extend(event.payload.get("warnings", []))
        await self._transition(
            record,
            OperationStatus.RISK_APPROVED,
            expected_risk_request_id=record.risk_request_event_id,
        )
        await self.repository.mark_event_processed(
            event.event_id,
            event.event_type,
            event.source_agent.value,
        )
        return await self._continue_risk_approved(record, event.event_id)

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

    async def update_parameters(
        self,
        operation_id: str,
        request: UpdateOperationRequest,
        operator: OperatorContext,
    ) -> OperationResponse:
        record = await self._require(operation_id)
        allowed_statuses = {
            OperationStatus.NEED_MORE_INFORMATION,
            OperationStatus.WAITING_RISK_REVIEW,
            OperationStatus.RISK_APPROVED,
            OperationStatus.PENDING_CONFIRMATION,
        }
        if record.status not in allowed_statuses:
            raise ConflictError(
                "OP_PARAM_INVALID",
                "当前状态不允许修改操作参数",
            )
        await self._transition(
            record,
            OperationStatus.RESOLVING_ENTITIES,
            actor_id=request.updated_by,
        )
        if record.risk_request_event_id:
            await self.repository.update_risk_review(
                record.risk_request_event_id,
                {"status": "superseded", "responded_at": utc_now()},
            )
        await self.state_store.delete(
            f"operator:confirmation:{record.operation_id}"
        )
        merged_params = {**record.params, **request.params}
        try:
            normalized, missing_fields = validate_operation_params(
                record.intent,
                merged_params,
            )
        except OperatorError as exc:
            record.error_code = exc.code
            await self._transition(
                record,
                OperationStatus.VALIDATION_FAILED,
                actor_id=request.updated_by,
            )
            await self._publish_result(record)
            return self._response(record, request.request_id, error=exc)
        if missing_fields:
            record.params = merged_params
            record.missing_fields = missing_fields
            await self._transition(
                record,
                OperationStatus.NEED_MORE_INFORMATION,
                actor_id=request.updated_by,
            )
            return self._response(record, request.request_id)
        previous_version = record.version
        record.version += 1
        record.params = normalized
        record.customer_id = normalized.get("customer_id", record.customer_id)
        record.params_hash = hash_params(normalized)
        record.missing_fields = []
        record.risk_result = None
        record.risk_request_event_id = None
        record.confirmation_required = requires_confirmation(
            record.intent,
            normalized,
        )
        await self.repository.add_version(record, request.updated_by)
        await self._transition(
            record,
            OperationStatus.VALIDATING,
            actor_id=request.updated_by,
            expected_version=previous_version,
        )
        try:
            check_permission(
                operator,
                record.intent,
                normalized.get("customer_id"),
                normalized,
            )
        except OperatorError as exc:
            record.error_code = exc.code
            await self._transition(
                record,
                OperationStatus.PERMISSION_DENIED,
                actor_id=request.updated_by,
            )
            await self._publish_result(record)
            return self._response(record, request.request_id, error=exc)
        await self._transition(
            record,
            OperationStatus.WAITING_RISK_REVIEW,
            actor_id=request.updated_by,
        )
        await self.risk_review_service.request_review(record)
        return self._response(record, request.request_id)

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

    async def authorize_access(
        self,
        operation_id: str,
        operator: OperatorContext,
    ) -> None:
        record = await self._require(operation_id)
        check_permission(
            operator,
            record.intent,
            record.customer_id,
            record.params,
        )
        if record.organization_id != operator.organization_id:
            raise PermissionDeniedError(
                "OP_ORGANIZATION_OUT_OF_SCOPE",
                "操作不属于当前组织",
            )

    async def reconcile(
        self,
        operation_id: str,
        request_id: str,
    ) -> OperationResponse:
        record = await self._require(operation_id)
        if record.status != OperationStatus.PENDING_VERIFICATION:
            raise ConflictError(
                "OP_STATUS_UNKNOWN",
                "操作当前不需要状态核查",
            )
        result = await self.tool_registry.get_status(operation_id)
        if not result:
            return self._response(record, request_id)
        record.result = result
        record.completed_at = utc_now()
        await self._transition(record, OperationStatus.SUCCEEDED)
        await self._publish_result(record)
        return self._response(record, request_id)

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
                expected_risk_request_id=record.risk_request_event_id,
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

    async def publish_event_error(
        self,
        source_event: AgentEvent,
        error: OperatorError,
    ) -> None:
        event = AgentEvent(
            event_id=new_id("EVT"),
            event_type="operation.request.rejected",
            source_agent=AgentId.OPERATOR,
            target_agents=[source_event.source_agent],
            correlation_id=source_event.event_id,
            operation_id=source_event.operation_id,
            task_id=source_event.task_id,
            session_id=source_event.session_id,
            customer_id=source_event.customer_id,
            intent=source_event.intent,
            payload={
                "status": "rejected",
                "error_code": error.code,
                "message": error.message,
                "source_event_id": source_event.event_id,
            },
        )
        await self.publisher.publish(EventChannel.AGENT_RESULT, event)

    async def claim_control_event(self, event: AgentEvent) -> None:
        if event.schema_version != "1.0":
            raise OperatorError(
                "OP_EVENT_SCHEMA_UNSUPPORTED",
                "不支持的控制事件版本",
            )
        if not event.expires_at or event.expires_at <= utc_now():
            raise OperatorError(
                "OP_EVENT_EXPIRED",
                "控制事件已过期或缺少有效期",
            )
        claimed = await self.repository.claim_event(
            event.event_id,
            event.event_type,
            event.source_agent.value,
        )
        if not claimed:
            raise ConflictError(
                "OP_EVENT_DUPLICATE",
                "控制事件已经处理",
            )

    async def complete_control_event(self, event_id: str) -> None:
        await self.repository.complete_event(event_id)

    async def expire_confirmations(self) -> int:
        operation_ids = await self.repository.find_expired_confirmations(
            utc_now()
        )
        expired_count = 0
        for operation_id in operation_ids:
            record = await self._require(operation_id)
            if record.status != OperationStatus.PENDING_CONFIRMATION:
                continue
            record.error_code = "OP_CONFIRMATION_EXPIRED"
            await self._transition(record, OperationStatus.EXPIRED)
            await self.state_store.delete(
                f"operator:confirmation:{operation_id}"
            )
            await self._publish_result(record)
            expired_count += 1
        return expired_count

    async def resume_ready_operations(self) -> int:
        resumed = 0
        recovery_before = utc_now() - timedelta(seconds=5)
        for operation_id in await self.repository.find_risk_approved(
            recovery_before
        ):
            record = await self._require(operation_id)
            if record.status != OperationStatus.RISK_APPROVED:
                continue
            await self._continue_risk_approved(
                record,
                f"RECOVER_{record.operation_id}",
            )
            resumed += 1
        for operation_id in await self.repository.find_confirmed(
            recovery_before
        ):
            record = await self._require(operation_id)
            if record.status != OperationStatus.CONFIRMED:
                continue
            await self._execute(
                record,
                f"RECOVER_{record.operation_id}",
            )
            resumed += 1
        return resumed

    async def reconcile_pending_operations(self) -> int:
        operation_ids = {
            *await self.repository.find_pending_verification(),
            *await self.repository.find_executing(),
        }
        reconciled = 0
        for operation_id in operation_ids:
            record = await self._require(operation_id)
            result = await self.tool_registry.get_status(operation_id)
            if not result and record.status == OperationStatus.EXECUTING:
                idempotency_key = f"{record.operation_id}:{record.version}"
                try:
                    result = await self.tool_registry.execute(
                        record.intent,
                        record.operation_id,
                        self._tool_params(record),
                        idempotency_key,
                    )
                except MockOperationTimeout:
                    record.error_code = "OP_MOCK_API_TIMEOUT"
                    await self._transition(
                        record,
                        OperationStatus.PENDING_VERIFICATION,
                    )
                    await self.repository.update_attempt_by_idempotency(
                        idempotency_key,
                        {
                            "status": "pending_verification",
                            "completed_at": utc_now(),
                        },
                    )
                    await self._publish_result(record)
                    reconciled += 1
                    continue
                except MockOperationError as exc:
                    record.error_code = exc.code
                    await self._transition(record, OperationStatus.FAILED)
                    await self.repository.update_attempt_by_idempotency(
                        idempotency_key,
                        {
                            "status": "failed",
                            "response_json": {
                                "code": exc.code,
                                "message": exc.message,
                            },
                            "completed_at": utc_now(),
                        },
                    )
                    await self._publish_result(record)
                    reconciled += 1
                    continue
            if not result:
                continue
            record.result = result
            record.completed_at = utc_now()
            await self._transition(record, OperationStatus.SUCCEEDED)
            await self.repository.update_attempt_by_idempotency(
                f"{record.operation_id}:{record.version}",
                {
                    "status": "succeeded",
                    "response_json": result,
                    "completed_at": utc_now(),
                },
            )
            await self._publish_result(record)
            reconciled += 1
        return reconciled

    async def _continue_risk_approved(
        self,
        record: OperationRecord,
        request_id: str,
    ) -> OperationResponse:
        if record.status != OperationStatus.RISK_APPROVED:
            raise ConflictError(
                "OP_CONCURRENT_MODIFICATION",
                "操作已不处于风控通过状态",
            )
        if not record.confirmation_required:
            return await self._execute(record, request_id)

        expires_at = record.confirmation_expires_at or (
            utc_now() + timedelta(seconds=self.confirmation_ttl_seconds)
        )
        remaining_seconds = max(
            1,
            int((expires_at - utc_now()).total_seconds()),
        )
        record.confirmation_expires_at = expires_at
        await self.state_store.put(
            f"operator:confirmation:{record.operation_id}",
            {
                "operation_id": record.operation_id,
                "version": record.version,
                "params_hash": record.params_hash,
                "expires_at": expires_at.isoformat(),
            },
            remaining_seconds,
        )
        await self._transition(
            record,
            OperationStatus.PENDING_CONFIRMATION,
        )
        await self._publish_status(record, "operation.pending_confirmation")
        return self._response(
            record,
            request_id,
            confirmation_expires_at=expires_at,
        )

    async def _execute(
        self,
        record: OperationRecord,
        request_id: str,
    ) -> OperationResponse:
        attempt_id = new_id("ATT")
        idempotency_key = f"{record.operation_id}:{record.version}"
        await self._transition(
            record,
            OperationStatus.EXECUTING,
            execution_attempt_values={
                "attempt_id": attempt_id,
                "operation_id": record.operation_id,
                "idempotency_key": idempotency_key,
                "tool_name": record.intent.value,
                "request_json": record.params,
                "response_json": None,
                "status": "executing",
                "started_at": utc_now(),
                "completed_at": None,
            },
        )
        await self.idempotency_service.acquire(record.operation_id, record.version)
        try:
            result = await self.tool_registry.execute(
                record.intent,
                record.operation_id,
                self._tool_params(record),
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
        return self._response(record, request_id)

    @staticmethod
    def _tool_params(record: OperationRecord) -> dict[str, Any]:
        return {
            **record.params,
            "_organization_id": record.organization_id,
            "_operator_id": record.operator_id,
        }

    async def _transition(
        self,
        record: OperationRecord,
        target: OperationStatus,
        *,
        actor_id: str | None = None,
        detail: dict[str, Any] | None = None,
        expected_version: int | None = None,
        expected_risk_request_id: str | None = None,
        execution_attempt_values: dict[str, Any] | None = None,
    ) -> None:
        old = record.status
        try:
            assert_transition(old, target)
        except InvalidStateTransition as exc:
            raise ConflictError(
                "OP_INVALID_STATE_TRANSITION",
                str(exc),
            ) from exc
        committed_events = [
            (
                EventChannel.AGENT_RESULT,
                self._state_committed_event(record, target),
            )
        ]
        if (
            target == OperationStatus.SUCCEEDED
            and record.result
            and "transaction_id" in record.result
        ):
            committed_events.append(
                (
                    EventChannel.TRANSACTION_EVENT,
                    self._transaction_event(record),
                )
            )
        changed = await self.repository.transition(
            record,
            old,
            target,
            expected_version=(
                record.version
                if expected_version is None
                else expected_version
            ),
            expected_risk_request_id=expected_risk_request_id,
            audit_values={
                "operation_id": record.operation_id,
                "event_type": f"operation.{target.value}",
                "actor_type": "operator" if actor_id else "agent",
                "actor_id": actor_id or AgentId.OPERATOR.value,
                "old_status": old.value,
                "new_status": target.value,
                "detail_json": detail or {},
                "trace_id": record.request_id,
                "created_at": utc_now(),
            },
            outbox_values=[
                {
                    "event_id": event.event_id,
                    "channel": channel.value,
                    "payload": event.model_dump(mode="json"),
                }
                for channel, event in committed_events
            ],
            execution_attempt_values=execution_attempt_values,
        )
        if not changed:
            latest = await self.repository.get(record.operation_id)
            raise ConflictError(
                "OP_CONCURRENT_MODIFICATION",
                "操作状态已被其他请求更新",
                details={
                    "expected_status": old.value,
                    "actual_status": latest.status.value if latest else None,
                },
            )
        record.status = target
        for channel, event in committed_events:
            await self.publisher.publish(channel, event)

    def _state_committed_event(
        self,
        record: OperationRecord,
        target: OperationStatus,
    ) -> AgentEvent:
        targets = [record.source_agent]
        if AgentId.RISK not in targets:
            targets.append(AgentId.RISK)
        return AgentEvent(
            event_id=new_id("EVT"),
            event_type=f"operation.{target.value}",
            source_agent=AgentId.OPERATOR,
            target_agents=targets,
            correlation_id=record.operation_id,
            operation_id=record.operation_id,
            task_id=record.task_id,
            session_id=record.session_id,
            customer_id=record.customer_id,
            intent=record.intent,
            payload={
                "status": target.value,
                "version": record.version,
                "result": record.result,
                "error_code": record.error_code,
                "warnings": record.warnings,
            },
        )

    def _transaction_event(self, record: OperationRecord) -> AgentEvent:
        return AgentEvent(
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
            params_hash=record.params_hash,
            params=record.params,
            missing_fields=record.missing_fields,
            warnings=record.warnings,
            confirmation_required=record.confirmation_required,
            confirmation_expires_at=(
                confirmation_expires_at or record.confirmation_expires_at
            ),
            result=record.result,
            reply=reply_map.get(record.status, "操作处理中。"),
            error=error_detail,
        )
