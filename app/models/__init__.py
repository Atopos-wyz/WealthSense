"""共享数据模型与错误定义。"""

from app.models.error_codes import ErrorCode, ErrorDefinition, get_error_definition

__all__ = ["ErrorCode", "ErrorDefinition", "get_error_definition"]
