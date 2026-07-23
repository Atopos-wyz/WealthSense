"""集中管理业务错误码。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from http import HTTPStatus


class ErrorCode(IntEnum):
    SUCCESS = 200
    INVALID_ARGUMENT = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    CONFLICT = 409
    INTERNAL_ERROR = 500

    LLM_CALL_FAILED = 1001
    KNOWLEDGE_NOT_FOUND = 1002
    SQL_GENERATION_FAILED = 1003
    RISK_RULE_TRIGGERED = 1004
    SUITABILITY_MISMATCH = 1005

    CONFIGURATION_ERROR = 1100
    DATABASE_CONNECTION_ERROR = 1101
    EXTERNAL_SERVICE_ERROR = 1102

    TOKEN_INVALID = 1201
    TOKEN_EXPIRED = 1202


@dataclass(frozen=True, slots=True)
class ErrorDefinition:
    code: ErrorCode
    message: str
    http_status: HTTPStatus


ERROR_DEFINITIONS: dict[ErrorCode, ErrorDefinition] = {
    ErrorCode.SUCCESS: ErrorDefinition(
        ErrorCode.SUCCESS, "success", HTTPStatus.OK
    ),
    ErrorCode.INVALID_ARGUMENT: ErrorDefinition(
        ErrorCode.INVALID_ARGUMENT, "请求参数错误", HTTPStatus.BAD_REQUEST
    ),
    ErrorCode.UNAUTHORIZED: ErrorDefinition(
        ErrorCode.UNAUTHORIZED, "未认证或认证信息无效", HTTPStatus.UNAUTHORIZED
    ),
    ErrorCode.FORBIDDEN: ErrorDefinition(
        ErrorCode.FORBIDDEN, "无权执行该操作", HTTPStatus.FORBIDDEN
    ),
    ErrorCode.NOT_FOUND: ErrorDefinition(
        ErrorCode.NOT_FOUND, "请求的资源不存在", HTTPStatus.NOT_FOUND
    ),
    ErrorCode.CONFLICT: ErrorDefinition(
        ErrorCode.CONFLICT, "资源状态冲突", HTTPStatus.CONFLICT
    ),
    ErrorCode.INTERNAL_ERROR: ErrorDefinition(
        ErrorCode.INTERNAL_ERROR, "服务内部错误", HTTPStatus.INTERNAL_SERVER_ERROR
    ),
    ErrorCode.LLM_CALL_FAILED: ErrorDefinition(
        ErrorCode.LLM_CALL_FAILED, "大模型服务不可用或调用超时", HTTPStatus.BAD_GATEWAY
    ),
    ErrorCode.KNOWLEDGE_NOT_FOUND: ErrorDefinition(
        ErrorCode.KNOWLEDGE_NOT_FOUND, "知识库未检索到相关内容", HTTPStatus.NOT_FOUND
    ),
    ErrorCode.SQL_GENERATION_FAILED: ErrorDefinition(
        ErrorCode.SQL_GENERATION_FAILED, "无法生成合法 SQL", HTTPStatus.UNPROCESSABLE_ENTITY
    ),
    ErrorCode.RISK_RULE_TRIGGERED: ErrorDefinition(
        ErrorCode.RISK_RULE_TRIGGERED, "操作触发风控规则", HTTPStatus.CONFLICT
    ),
    ErrorCode.SUITABILITY_MISMATCH: ErrorDefinition(
        ErrorCode.SUITABILITY_MISMATCH, "客户与产品适当性不匹配", HTTPStatus.CONFLICT
    ),
    ErrorCode.CONFIGURATION_ERROR: ErrorDefinition(
        ErrorCode.CONFIGURATION_ERROR, "应用配置无效", HTTPStatus.INTERNAL_SERVER_ERROR
    ),
    ErrorCode.DATABASE_CONNECTION_ERROR: ErrorDefinition(
        ErrorCode.DATABASE_CONNECTION_ERROR,
        "数据库连接失败",
        HTTPStatus.SERVICE_UNAVAILABLE,
    ),
    ErrorCode.EXTERNAL_SERVICE_ERROR: ErrorDefinition(
        ErrorCode.EXTERNAL_SERVICE_ERROR,
        "外部服务调用失败",
        HTTPStatus.BAD_GATEWAY,
    ),
    ErrorCode.TOKEN_INVALID: ErrorDefinition(
        ErrorCode.TOKEN_INVALID, "访问令牌无效", HTTPStatus.UNAUTHORIZED
    ),
    ErrorCode.TOKEN_EXPIRED: ErrorDefinition(
        ErrorCode.TOKEN_EXPIRED, "访问令牌已过期", HTTPStatus.UNAUTHORIZED
    ),
}


def get_error_definition(code: ErrorCode) -> ErrorDefinition:
    """返回指定错误码的标准定义。"""

    return ERROR_DEFINITIONS.get(code, ERROR_DEFINITIONS[ErrorCode.INTERNAL_ERROR])
