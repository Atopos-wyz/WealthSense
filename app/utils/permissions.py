"""Mock JWT 身份认证与可复用的 RBAC 权限依赖。"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import ExpiredSignatureError, InvalidTokenError
from pydantic import ValidationError

from app.config.settings import Settings, get_settings
from app.models.error_codes import ErrorCode
from app.models.schemas.auth import CurrentUser, Permission, TokenPayload, UserRole
from app.utils.exceptions import AuthenticationError, PermissionDeniedError

bearer_scheme = HTTPBearer(auto_error=False)

ROLE_PERMISSIONS: dict[UserRole, frozenset[Permission]] = {
    UserRole.CUSTOMER: frozenset(
        {
            Permission.CHAT_USE,
            Permission.KNOWLEDGE_READ,
            Permission.PRODUCT_READ,
            Permission.PROFILE_READ,
        }
    ),
    UserRole.ADVISOR: frozenset(
        {
            Permission.CHAT_USE,
            Permission.KNOWLEDGE_READ,
            Permission.PROFILE_READ,
            Permission.PROFILE_WRITE,
            Permission.PRODUCT_READ,
            Permission.PRODUCT_RECOMMEND,
            Permission.WORKORDER_READ,
        }
    ),
    UserRole.RISK_OFFICER: frozenset(
        {
            Permission.CHAT_USE,
            Permission.PROFILE_READ,
            Permission.RISK_READ,
            Permission.RISK_HANDLE,
            Permission.WORKORDER_READ,
            Permission.WORKORDER_MANAGE,
        }
    ),
    UserRole.ANALYST: frozenset(
        {
            Permission.CHAT_USE,
            Permission.ANALYTICS_READ,
            Permission.PROFILE_READ,
            Permission.PRODUCT_READ,
            Permission.RISK_READ,
            Permission.WORKORDER_READ,
        }
    ),
    UserRole.CUSTOMER_MANAGER: frozenset(
        {
            Permission.CHAT_USE,
            Permission.PROFILE_READ,
            Permission.PROFILE_WRITE,
            Permission.PRODUCT_READ,
            Permission.OPERATION_EXECUTE,
            Permission.WORKORDER_READ,
            Permission.WORKORDER_MANAGE,
        }
    ),
    UserRole.ADMIN: frozenset(Permission),
}


def permissions_for_roles(roles: Iterable[UserRole]) -> frozenset[Permission]:
    resolved: set[Permission] = set()
    for role in roles:
        resolved.update(ROLE_PERMISSIONS.get(role, ()))
    return frozenset(resolved)


def create_access_token(
    *,
    subject: str,
    roles: Iterable[UserRole],
    permissions: Iterable[Permission] = (),
    expires_delta: timedelta | None = None,
    settings: Settings | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """创建与 RBAC 权限依赖兼容的开发环境 JWT。"""

    active_settings = settings or get_settings()
    now = datetime.now(timezone.utc)
    expires = now + (
        expires_delta
        or timedelta(minutes=active_settings.jwt_access_token_expire_minutes)
    )
    payload = dict(extra_claims or {})
    payload.update(
        {
            "sub": subject,
            "roles": [role.value for role in roles],
            "permissions": [permission.value for permission in permissions],
            "iat": now,
            "exp": expires,
            "iss": active_settings.jwt_issuer,
            "aud": active_settings.jwt_audience,
        }
    )
    return jwt.encode(
        payload,
        active_settings.jwt_secret_key.get_secret_value(),
        algorithm=active_settings.jwt_algorithm,
    )


def decode_access_token(
    token: str,
    *,
    settings: Settings | None = None,
) -> CurrentUser:
    active_settings = settings or get_settings()
    try:
        raw_payload = jwt.decode(
            token,
            active_settings.jwt_secret_key.get_secret_value(),
            algorithms=[active_settings.jwt_algorithm],
            audience=active_settings.jwt_audience,
            issuer=active_settings.jwt_issuer,
        )
        payload = TokenPayload.model_validate(raw_payload)
    except ExpiredSignatureError as exc:
        raise AuthenticationError(code=ErrorCode.TOKEN_EXPIRED) from exc
    except (InvalidTokenError, ValidationError) as exc:
        raise AuthenticationError(code=ErrorCode.TOKEN_INVALID) from exc

    permissions = set(permissions_for_roles(payload.roles))
    permissions.update(payload.permissions)
    return CurrentUser(
        user_id=payload.sub,
        roles=frozenset(payload.roles),
        permissions=frozenset(permissions),
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError()
    return decode_access_token(credentials.credentials, settings=settings)


def require_roles(*allowed_roles: UserRole):
    """返回允许任一指定角色访问的 FastAPI 依赖。"""

    async def dependency(
        current_user: CurrentUser = Depends(get_current_user),
    ) -> CurrentUser:
        if not current_user.has_role(*allowed_roles):
            raise PermissionDeniedError()
        return current_user

    return dependency


def require_permissions(*required_permissions: Permission):
    """返回要求具备全部指定权限的 FastAPI 依赖。"""

    async def dependency(
        current_user: CurrentUser = Depends(get_current_user),
    ) -> CurrentUser:
        if not current_user.has_permission(*required_permissions):
            raise PermissionDeniedError()
        return current_user

    return dependency
