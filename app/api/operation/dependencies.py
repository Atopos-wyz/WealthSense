from typing import Annotated

from fastapi import Depends, Header, Request

from app.container import AppContainer
from app.models.schemas.operation import OperatorContext


def get_container(request: Request) -> AppContainer:
    return request.app.state.container


def get_operator(
    x_operator_id: Annotated[str, Header()] = "CUSTOMER001",
    x_operator_role: Annotated[str, Header()] = "customer",
    x_organization_id: Annotated[str, Header()] = "ORG001",
) -> OperatorContext:
    return OperatorContext(
        operator_id=x_operator_id,
        role=x_operator_role,
        organization_id=x_organization_id,
    )


ContainerDependency = Annotated[AppContainer, Depends(get_container)]
OperatorDependency = Annotated[OperatorContext, Depends(get_operator)]

