"""检索优先（Retrieve-then-Generate）的智能客服 Agent。"""

from __future__ import annotations

import json
from time import perf_counter

from app.agent.core import AgentBase, Intent
from app.models.schemas.chat import (
    ChatRequest,
    ChatResponse,
    SessionMessage,
    SourceReference,
    ToolCallRecord,
)
from app.service.knowledge import KnowledgeService
from app.service.llm import LanguageModelClient
from app.service.memory import SessionMemoryService


class CustomerAgent(AgentBase):
    FALLBACK_REPLY = (
        "抱歉，我暂时无法回答这个问题。"
        "建议您拨打客服热线400-XXX-XXXX咨询人工客服。"
    )

    def __init__(
        self,
        *,
        memory: SessionMemoryService,
        knowledge: KnowledgeService,
        llm: LanguageModelClient,
    ) -> None:
        super().__init__(agent_type="customer", memory=memory)
        self._knowledge = knowledge
        self._llm = llm

    @property
    def intent_threshold(self) -> float:
        return 0.6

    async def classify_intent(self, message: str) -> Intent:
        if self._llm is not None and self._llm.available:
            try:
                raw = await self._llm.chat(
                    system=(
                        "你是金融智能客服意图分类器。严格按以下定义分类："
                        "product_inquiry=询问具体金融产品、收益或风险；"
                        "policy_explain=询问法规、政策、监管或合规；"
                        "faq=询问开户、申购、赎回、手续费、办理流程或到账/确认时间；"
                        "chitchat=问候、感谢、告别或与业务无关的闲聊；"
                        "transfer_human=明确要求人工客服。"
                        "示例：‘基金申购后多久确认’必须分类为faq；"
                        "‘有什么稳健型理财产品’分类为product_inquiry。"
                        "只能输出JSON对象，格式为"
                        '{"intent":"faq","confidence":0.9}，不要解释。'
                    ),
                    user=message,
                    temperature=0,
                )
                payload = self._parse_json_object(raw)
                name = str(payload["intent"])
                confidence = float(payload["confidence"])
                if name in {
                    "product_inquiry",
                    "policy_explain",
                    "faq",
                    "chitchat",
                    "transfer_human",
                }:
                    return Intent(name, max(0.0, min(confidence, 1.0)))
            except Exception:
                pass
        return self._classify_by_keywords(message)

    @staticmethod
    def _classify_by_keywords(message: str) -> Intent:
        normalized = message.lower()
        if any(keyword in normalized for keyword in ("转人工", "人工客服", "找客服")):
            return Intent("transfer_human", 0.99)
        if any(keyword in normalized for keyword in ("你好", "您好", "谢谢", "再见")):
            return Intent("chitchat", 0.95)
        if any(
            keyword in normalized
            for keyword in ("政策", "法规", "监管", "合规", "资管新规", "反洗钱")
        ):
            return Intent("policy_explain", 0.92)
        if any(
            keyword in normalized
            for keyword in ("怎么", "多久", "流程", "手续费", "开户", "赎回", "申购")
        ):
            return Intent("faq", 0.88)
        if any(
            keyword in normalized
            for keyword in (
                "产品",
                "基金",
                "理财",
                "收益",
                "风险",
                "起投",
                "年化",
                "高净值",
                "企业金融",
            )
        ):
            return Intent("product_inquiry", 0.9)
        return Intent("chitchat", 0.55)

    async def respond(
        self,
        request: ChatRequest,
        history: list[SessionMessage],
        intent: Intent,
    ) -> ChatResponse:
        if intent.name == "transfer_human":
            return ChatResponse(
                reply="正在为您转接人工客服...",
                intent=intent.name,
                confidence=intent.confidence,
                session_id=request.session_id,
            )
        if intent.name == "chitchat":
            reply = await self._chitchat_reply(request.message)
            return ChatResponse(
                reply=reply,
                intent=intent.name,
                confidence=intent.confidence,
                session_id=request.session_id,
                suggestions=["您可以咨询基金、理财产品、业务流程或金融政策"],
            )

        knowledge_type = {
            "product_inquiry": "产品说明",
            "policy_explain": "政策法规",
            "faq": "FAQ",
        }[intent.name]
        top_k = 3 if knowledge_type == "FAQ" else 5
        min_score = 0.75 if knowledge_type == "FAQ" else 0.7
        started = perf_counter()
        results = await self._knowledge.search(
            query=request.message,
            top_k=top_k,
            min_score=min_score,
            knowledge_type=knowledge_type,
        )
        duration_ms = (perf_counter() - started) * 1000
        tool_call = ToolCallRecord(
            tool_name="rag_search",
            status="success",
            execution_time_ms=duration_ms,
            parameters={
                "collection_type": knowledge_type,
                "top_k": top_k,
                "min_score": min_score,
            },
        )
        if not results:
            return ChatResponse(
                reply=self.FALLBACK_REPLY,
                tool_calls=[tool_call],
                intent=intent.name,
                confidence=intent.confidence,
                session_id=request.session_id,
                suggestions=["转人工客服"],
            )

        sources = [
            SourceReference(
                source=result.source,
                title=result.title,
                score=result.score,
                source_id=result.source_id,
            )
            for result in results
        ]
        if intent.name == "faq":
            reply = self._faq_answer(results[0].content)
        else:
            reply = await self._knowledge_answer(
                request.message,
                history,
                results,
            )
        citations = " ".join(
            f"【来源：《{source.source}》{source.title}】"
            for source in sources[:3]
        )
        if citations not in reply:
            reply = f"{reply.rstrip()}\n\n{citations}"
        return ChatResponse(
            reply=reply,
            source_references=sources,
            tool_calls=[tool_call],
            intent=intent.name,
            confidence=intent.confidence,
            session_id=request.session_id,
            suggestions=["继续了解风险等级", "查看申购与赎回流程"],
        )

    async def _chitchat_reply(self, message: str) -> str:
        if not self._llm.available:
            return "您好，我是XX科技智能财富管家。您可以咨询金融产品、业务流程或政策问题。"
        try:
            return await self._llm.chat(
                system=(
                    "你是XX科技的智能财富管家。对问候简短友好回复，"
                    "并引导用户咨询金融产品、业务流程或政策；不要编造业务信息。"
                ),
                user=message,
                temperature=0.3,
            )
        except Exception:
            return "您好，我是XX科技智能财富管家。您可以咨询金融产品、业务流程或政策问题。"

    async def _knowledge_answer(self, message, history, results) -> str:
        if not self._llm.available:
            return "\n\n".join(result.content for result in results[:2])
        context = "\n\n".join(
            f"【来源{i + 1}】{result.source} / {result.title}\n{result.content}"
            for i, result in enumerate(results)
        )
        recent = "\n".join(
            f"{item.role}: {item.content}" for item in history[-6:]
        )
        try:
            return await self._llm.chat(
                system=(
                    "你是XX科技的智能财富管家。仅基于给定知识回答，不得编造；"
                    "知识不足时明确告知并建议联系人工客服；语言友好、专业、简洁。"
                ),
                user=f"最近对话：\n{recent}\n\n知识：\n{context}\n\n问题：{message}",
                temperature=0.3,
            )
        except Exception:
            return "\n\n".join(result.content for result in results[:2])

    @staticmethod
    def _faq_answer(content: str) -> str:
        marker = "回答："
        return content.split(marker, 1)[1].strip() if marker in content else content

    @staticmethod
    def _parse_json_object(raw: str) -> dict:
        text = raw.strip()
        if text.startswith("```"):
            text = text.removeprefix("```json").removeprefix("```")
            text = text.removesuffix("```").strip()
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("LLM 意图分类结果不是 JSON 对象")
        return payload
