"""功能设计文档定义的统一 Agent 执行骨架。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.models.schemas.chat import ChatRequest, ChatResponse, SessionMessage
from app.service.memory import SessionMemoryService


@dataclass(frozen=True, slots=True)
class Intent:
    name: str
    confidence: float


class AgentBase(ABC):
    def __init__(
        self,
        *,
        agent_type: str,
        memory: SessionMemoryService,
    ) -> None:
        self.agent_type = agent_type
        self.memory = memory

    async def handle(self, request: ChatRequest) -> ChatResponse:
        history = await self.memory.recall(request.session_id)
        intent = await self.classify_intent(request.message)
        if intent.confidence < self.intent_threshold:
            response = self.clarification_response(request, intent)
        else:
            response = await self.respond(request, history, intent)
        await self.memory.append_exchange(
            session_id=request.session_id,
            user_id=request.user_id,
            agent_type=self.agent_type,
            user_message=request.message,
            assistant_message=response.reply,
            response_metadata={
                "intent": response.intent,
                "confidence": response.confidence,
                "source_references": [
                    source.model_dump(mode="json")
                    for source in response.source_references
                ],
                "sql": response.sql,
            },
        )
        return response

    @property
    @abstractmethod
    def intent_threshold(self) -> float: ...

    @abstractmethod
    async def classify_intent(self, message: str) -> Intent: ...

    @abstractmethod
    async def respond(
        self,
        request: ChatRequest,
        history: list[SessionMessage],
        intent: Intent,
    ) -> ChatResponse: ...

    def clarification_response(
        self,
        request: ChatRequest,
        intent: Intent,
    ) -> ChatResponse:
        return ChatResponse(
            reply="我还不能准确判断您的需求，请补充要查询的对象或时间范围。",
            intent=intent.name,
            confidence=intent.confidence,
            session_id=request.session_id,
            suggestions=["请说明具体产品、客户ID或查询指标"],
        )
