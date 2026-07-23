"""生成-校验-执行-解读范式的数据分析 Agent。"""

from __future__ import annotations

import hashlib
import json
from time import perf_counter

from app.agent.core import AgentBase, Intent
from app.dao.redis import RedisConnectionManager
from app.models.schemas.chat import (
    ChatRequest,
    ChatResponse,
    SessionMessage,
    ToolCallRecord,
)
from app.service.llm import LanguageModelClient
from app.service.memory import SessionMemoryService
from app.tool.sql import AnalystIntent, NL2SQLTool, SQLExecutor
from app.tool.sql.safety import UnsafeSQLError


class AnalystAgent(AgentBase):
    def __init__(
        self,
        *,
        memory: SessionMemoryService,
        redis: RedisConnectionManager,
        nl2sql: NL2SQLTool,
        executor: SQLExecutor,
        llm: LanguageModelClient,
        cache_ttl_seconds: int,
    ) -> None:
        super().__init__(agent_type="analyst", memory=memory)
        self._redis = redis
        self._nl2sql = nl2sql
        self._executor = executor
        self._llm = llm
        self._cache_ttl_seconds = cache_ttl_seconds

    @property
    def intent_threshold(self) -> float:
        return 0.6

    async def classify_intent(self, message: str) -> Intent:
        if self._llm.available:
            try:
                raw = await self._llm.chat(
                    system=(
                        "你是金融数据查询意图分类器。只能从 holdings_query、"
                        "return_stats、transaction_query、customer_stats、"
                        "product_stats、workorder_query 中选择。"
                        "只输出JSON对象，格式为"
                        '{"intent":"customer_stats","confidence":0.9}，不要解释。'
                    ),
                    user=message,
                    temperature=0,
                )
                payload = self._parse_json_object(raw)
                name = str(payload["intent"])
                confidence = float(payload["confidence"])
                if name in {item.value for item in AnalystIntent}:
                    return Intent(name, max(0.0, min(confidence, 1.0)))
            except Exception:
                pass
        intent, confidence = self._nl2sql.classify_intent(message)
        return Intent(intent.value, confidence)

    async def respond(
        self,
        request: ChatRequest,
        history: list[SessionMessage],
        intent: Intent,
    ) -> ChatResponse:
        cache_key = "nl2sql:cache:" + hashlib.sha256(
            request.message.encode("utf-8")
        ).hexdigest()
        cached = await self._read_cache(cache_key)
        if cached is not None:
            return ChatResponse(
                reply=cached["reply"],
                tool_calls=[
                    ToolCallRecord(
                        tool_name="nl2sql_cache",
                        status="success",
                        execution_time_ms=0,
                    )
                ],
                intent=intent.name,
                confidence=intent.confidence,
                session_id=request.session_id,
                sql=cached["sql"],
                query_result=cached["query_result"],
            )

        try:
            typed_intent = AnalystIntent(intent.name)
        except ValueError:
            typed_intent, _ = self._nl2sql.classify_intent(request.message)
        calls: list[ToolCallRecord] = []
        started = perf_counter()
        sql, _schema = await self._nl2sql.generate(request.message, typed_intent)
        calls.append(
            ToolCallRecord(
                tool_name="nl2sql",
                status="success",
                execution_time_ms=(perf_counter() - started) * 1000,
                parameters={"intent": intent.name},
            )
        )
        started = perf_counter()
        try:
            execution = await self._executor.execute(sql)
        except UnsafeSQLError:
            calls.append(
                ToolCallRecord(
                    tool_name="sql_safety",
                    status="failed",
                    execution_time_ms=(perf_counter() - started) * 1000,
                )
            )
            return ChatResponse(
                reply="不允许执行该操作",
                tool_calls=calls,
                intent=intent.name,
                confidence=intent.confidence,
                session_id=request.session_id,
            )
        except Exception:
            calls.append(
                ToolCallRecord(
                    tool_name="sql_executor",
                    status="failed",
                    execution_time_ms=(perf_counter() - started) * 1000,
                )
            )
            return ChatResponse(
                reply="SQL执行失败，请补充或调整查询条件后重试。",
                tool_calls=calls,
                intent=intent.name,
                confidence=intent.confidence,
                session_id=request.session_id,
                sql=sql,
            )
        calls.extend(
            [
                ToolCallRecord(
                    tool_name="sql_safety",
                    status="success",
                    execution_time_ms=0,
                ),
                ToolCallRecord(
                    tool_name="sql_executor",
                    status="success",
                    execution_time_ms=(perf_counter() - started) * 1000,
                ),
            ]
        )
        reply = await self._interpret(
            request.message,
            execution.sql,
            execution.rows,
        )
        response = ChatResponse(
            reply=reply,
            tool_calls=calls,
            intent=intent.name,
            confidence=intent.confidence,
            session_id=request.session_id,
            sql=execution.sql,
            query_result=execution.rows,
            suggestions=["补充时间范围", "按产品类型或客户分组统计"],
        )
        await self._write_cache(
            cache_key,
            {
                "reply": response.reply,
                "sql": response.sql,
                "query_result": response.query_result,
            },
        )
        return response

    async def _interpret(
        self,
        question: str,
        sql: str,
        rows: list[dict],
    ) -> str:
        if self._llm.available:
            try:
                return await self._llm.chat(
                    system=(
                        "你是金融数据分析专家。根据查询问题、SQL、前10行结果和"
                        "总行数做简洁客观解读，不得补充结果中不存在的数据。"
                    ),
                    user=(
                        f"问题：{question}\nSQL：{sql}\n"
                        f"总行数：{len(rows)}\n前10行："
                        f"{json.dumps(rows[:10], ensure_ascii=False, default=str)}"
                    ),
                    temperature=0,
                )
            except Exception:
                pass
        if not rows:
            return "查询已完成，当前条件下没有符合的数据。"
        if len(rows) == 1 and len(rows[0]) == 1:
            key, value = next(iter(rows[0].items()))
            return f"查询已完成，{key}为{value}。"
        return f"查询已完成，共返回{len(rows)}行数据，结果见 query_result。"

    async def _read_cache(self, key: str) -> dict | None:
        try:
            await self._redis.connect()
            value = await self._redis.client.get(key)
            return json.loads(value) if value else None
        except Exception:
            return None

    async def _write_cache(self, key: str, value: dict) -> None:
        try:
            await self._redis.connect()
            await self._redis.client.set(
                key,
                json.dumps(value, ensure_ascii=False, default=str),
                ex=self._cache_ttl_seconds,
            )
        except Exception:
            pass

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
