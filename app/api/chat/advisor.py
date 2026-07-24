"""投顾 Agent 普通响应与 SSE 流式响应接口。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.advisor import AdvisorAgent
from app.config.database import get_session
from app.models.schemas import ApiResponse
from app.models.schemas.advisor import (
    AdvisorChatRequest,
    AdvisorChatResponse,
    AdvisorStreamEvent,
)
from app.utils.logger import get_trace_id
from app.view.response import success_response


router = APIRouter(prefix="/api/chat", tags=["投顾 Agent"])


def get_advisor_agent(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdvisorAgent:
    return AdvisorAgent(session)


@router.post(
    "/advisor",
    response_model=ApiResponse[AdvisorChatResponse],
    summary="投顾 Agent 对话",
)
async def advisor_chat(
    payload: AdvisorChatRequest,
    agent: Annotated[AdvisorAgent, Depends(get_advisor_agent)],
) -> ApiResponse[AdvisorChatResponse]:
    return success_response(await agent.chat(payload))


@router.post(
    "/advisor/stream",
    summary="投顾 Agent SSE 流式对话",
    response_class=StreamingResponse,
)
async def advisor_chat_stream(
    payload: AdvisorChatRequest,
    agent: Annotated[AdvisorAgent, Depends(get_advisor_agent)],
) -> StreamingResponse:
    return StreamingResponse(
        _stream_response(payload, agent),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _stream_response(
    payload: AdvisorChatRequest,
    agent: AdvisorAgent,
) -> AsyncIterator[str]:
    yield _sse(
        AdvisorStreamEvent(
            event="started",
            data={
                "session_id": payload.session_id,
                "trace_id": get_trace_id(),
            },
        )
    )
    try:
        result = await agent.chat(payload)
        yield _sse(
            AdvisorStreamEvent(
                event="intent",
                data={
                    "intent": result.intent.value,
                    "route": result.route.value,
                    "profile_found": result.profile_found,
                },
            )
        )
        for recommendation in result.recommendations:
            yield _sse(
                AdvisorStreamEvent(
                    event="recommendation",
                    data=recommendation.model_dump(mode="json"),
                )
            )
        for index in range(0, len(result.reply), 24):
            yield _sse(
                AdvisorStreamEvent(
                    event="message",
                    data={"delta": result.reply[index : index + 24]},
                )
            )
        yield _sse(
            AdvisorStreamEvent(
                event="completed",
                data=result.model_dump(mode="json"),
            )
        )
    except Exception as exc:
        yield _sse(
            AdvisorStreamEvent(
                event="error",
                data={
                    "message": "投顾处理失败",
                    "error_type": type(exc).__name__,
                    "trace_id": get_trace_id(),
                },
            )
        )


def _sse(event: AdvisorStreamEvent) -> str:
    payload = json.dumps(
        event.data,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"event: {event.event}\ndata: {payload}\n\n"
