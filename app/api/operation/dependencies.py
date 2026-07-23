from typing import Annotated

from fastapi import Depends, Header, Request

from app.container import AppContainer
from app.models.schemas.operation import OperatorContext
from app.utils.exceptions import PermissionDeniedError
from app.utils.security import decode_hs256_jwt


def get_container(request: Request) -> AppContainer:
    return request.app.state.container


def get_operator(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> OperatorContext:
    if not authorization or not authorization.startswith("Bearer "):
        raise PermissionDeniedError(
            "OP_AUTH_REQUIRED",
            "缺少Bearer身份令牌",
        )
    settings = request.app.state.container.settings
    claims = decode_hs256_jwt(
        authorization.removeprefix("Bearer ").strip(),
        settings.jwt_secret,
        settings.jwt_issuer,
    )
    return OperatorContext(
        operator_id=str(claims["sub"]),
        role=str(claims["role"]),
        organization_id=str(claims["organization_id"]),
        allowed_customer_ids=set(claims.get("customer_ids", [])),
        allowed_account_ids=set(claims.get("account_ids", [])),
        allowed_holding_ids=set(claims.get("holding_ids", [])),
    )


ContainerDependency = Annotated[AppContainer, Depends(get_container)]
OperatorDependency = Annotated[OperatorContext, Depends(get_operator)]
