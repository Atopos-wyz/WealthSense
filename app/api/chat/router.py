"""客服与数据分析 Agent 对话入口。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.agent import AnalystAgent, CustomerAgent
from app.dependencies import (
    get_analyst_agent,
    get_customer_agent,
    get_memory_service,
)
from app.models.schemas import (
    AgentType,
    ApiResponse,
    ChatRequest,
    ChatResponse,
    CurrentUser,
    Permission,
    SessionMessage,
)
from app.service.memory import SessionMemoryService
from app.utils.exceptions import PermissionDeniedError
from app.utils.permissions import require_permissions
from app.view.response import success_response

router = APIRouter(prefix="/api/chat", tags=["chat"])

ChatUser = Annotated[
    CurrentUser,
    Depends(require_permissions(Permission.CHAT_USE)),
]
AnalystUser = Annotated[
    CurrentUser,
    Depends(
        require_permissions(
            Permission.CHAT_USE,
            Permission.ANALYTICS_READ,
        )
    ),
]


def _validate_actor(request: ChatRequest, user: CurrentUser) -> None:
    if request.user_id != user.user_id and not user.has_permission(Permission.ADMIN):
        raise PermissionDeniedError("不能以其他用户身份发起对话")


@router.post("", response_model=ApiResponse[ChatResponse])
async def chat(
    request: ChatRequest,
    user: ChatUser,
    customer_agent: CustomerAgent = Depends(get_customer_agent),
    analyst_agent: AnalystAgent = Depends(get_analyst_agent),
) -> ApiResponse[ChatResponse]:
    _validate_actor(request, user)
    if request.agent_type == AgentType.ANALYST:
        if not user.has_permission(Permission.ANALYTICS_READ):
            raise PermissionDeniedError()
        response = await analyst_agent.handle(request)
    else:
        response = await customer_agent.handle(request)
    return success_response(response)


@router.post("/customer", response_model=ApiResponse[ChatResponse])
async def customer_chat(
    request: ChatRequest,
    user: ChatUser,
    agent: CustomerAgent = Depends(get_customer_agent),
) -> ApiResponse[ChatResponse]:
    _validate_actor(request, user)
    request.agent_type = AgentType.CUSTOMER
    return success_response(await agent.handle(request))


@router.post("/analyst", response_model=ApiResponse[ChatResponse])
async def analyst_chat(
    request: ChatRequest,
    user: AnalystUser,
    agent: AnalystAgent = Depends(get_analyst_agent),
) -> ApiResponse[ChatResponse]:
    _validate_actor(request, user)
    request.agent_type = AgentType.ANALYST
    return success_response(await agent.handle(request))


@router.get(
    "/session/{session_id}/history",
    response_model=ApiResponse[list[SessionMessage]],
)
async def session_history(
    session_id: str,
    _: ChatUser,
    memory: SessionMemoryService = Depends(get_memory_service),
) -> ApiResponse[list[SessionMessage]]:
    return success_response(await memory.recall(session_id))
