"""共享身份认证与权限校验数据模型。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class UserRole(str, Enum):
    CUSTOMER = "customer"
    ADVISOR = "advisor"
    RISK_OFFICER = "risk_officer"
    ANALYST = "analyst"
    CUSTOMER_MANAGER = "customer_manager"
    ADMIN = "admin"


class Permission(str, Enum):
    CHAT_USE = "chat:use"
    KNOWLEDGE_READ = "knowledge:read"
    KNOWLEDGE_MANAGE = "knowledge:manage"
    PROFILE_READ = "profile:read"
    PROFILE_WRITE = "profile:write"
    PRODUCT_READ = "product:read"
    PRODUCT_RECOMMEND = "product:recommend"
    ANALYTICS_READ = "analytics:read"
    OPERATION_EXECUTE = "operation:execute"
    RISK_READ = "risk:read"
    RISK_HANDLE = "risk:handle"
    WORKORDER_READ = "workorder:read"
    WORKORDER_MANAGE = "workorder:manage"
    ADMIN = "admin:*"


class TokenPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sub: str = Field(min_length=1)
    roles: set[UserRole] = Field(default_factory=set)
    permissions: set[Permission] = Field(default_factory=set)
    exp: datetime | None = None
    iat: datetime | None = None
    iss: str | None = None
    aud: str | list[str] | None = None


class CurrentUser(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str
    roles: frozenset[UserRole] = Field(default_factory=frozenset)
    permissions: frozenset[Permission] = Field(default_factory=frozenset)

    def has_role(self, *roles: UserRole) -> bool:
        return bool(self.roles.intersection(roles))

    def has_permission(self, *permissions: Permission) -> bool:
        return (
            UserRole.ADMIN in self.roles
            or Permission.ADMIN in self.permissions
            or set(permissions).issubset(self.permissions)
        )
