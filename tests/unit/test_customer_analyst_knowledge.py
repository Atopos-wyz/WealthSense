from __future__ import annotations

import asyncio

import pytest

from app.agent.analyst import AnalystAgent
from app.agent.customer import CustomerAgent
from app.models.schemas.chat import AgentType, ChatRequest
from app.tool.document import DocumentParser
from app.tool.sql import AnalystIntent, NL2SQLTool, SQLSafetyTool
from app.tool.sql.safety import UnsafeSQLError


def test_faq_parser_keeps_each_qa_pair_as_one_chunk() -> None:
    parser = DocumentParser(chunk_size=512, chunk_overlap=64)
    chunks = parser.parse_bytes(
        "faq.txt",
        "问题一?\t答案一。\n问题二?\t答案二。\n".encode(),
    )

    assert len(chunks) == 2
    assert chunks[0].title == "问题一?"
    assert chunks[0].content == "问题：问题一?\n回答：答案一。"


def test_markdown_parser_preserves_heading_and_overlap() -> None:
    parser = DocumentParser(chunk_size=80, chunk_overlap=10)
    chunks = parser.parse_bytes(
        "manual.md",
        ("# 产品手册\n\n## 风险说明\n\n" + "稳健产品说明。" * 30).encode(),
    )

    assert len(chunks) > 1
    assert all("产品手册 > 风险说明" in chunk.title for chunk in chunks)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE fin_product",
        "DELETE FROM fin_product",
        "SELECT * FROM fin_product; SELECT * FROM sys_user",
        "SELECT SLEEP(10)",
        "SELECT * FROM fin_product FOR UPDATE",
    ],
)
def test_sql_safety_rejects_non_read_only_sql(sql: str) -> None:
    with pytest.raises(UnsafeSQLError):
        SQLSafetyTool(max_rows=100).prepare(sql)


def test_sql_safety_adds_and_clamps_limit() -> None:
    safety = SQLSafetyTool(max_rows=100)

    assert safety.prepare("SELECT * FROM fin_product").endswith("LIMIT 100")
    assert safety.prepare("SELECT * FROM fin_product LIMIT 500").endswith(
        "LIMIT 100"
    )


def test_template_nl2sql_covers_documented_aum_scenario() -> None:
    sql = NL2SQLTool._template_sql(
        "AUM超过100万的客户有多少个？",
        AnalystIntent.CUSTOMER_STATS,
    )

    assert "SELECT COUNT(*)" in sql
    assert "total_assets > 1000000" in sql


def test_customer_agent_intent_classifier_has_five_documented_routes() -> None:
    agent = CustomerAgent(memory=None, knowledge=None, llm=None)  # type: ignore[arg-type]

    assert asyncio.run(agent.classify_intent("有什么稳健型理财产品")).name == (
        "product_inquiry"
    )
    assert asyncio.run(agent.classify_intent("资管新规有什么影响")).name == (
        "policy_explain"
    )
    assert asyncio.run(agent.classify_intent("基金申购后多久确认")).name == "faq"
    assert asyncio.run(agent.classify_intent("你好")).name == "chitchat"
    assert asyncio.run(agent.classify_intent("我要转人工")).name == "transfer_human"


class _FakeIntentLLM:
    available = True

    async def chat(self, *, system: str, user: str, temperature: float) -> str:
        if "金融智能客服" in system:
            return '{"intent":"faq","confidence":0.93}'
        return '{"intent":"customer_stats","confidence":0.91}'


def test_agents_prefer_configured_llm_for_intent_classification() -> None:
    llm = _FakeIntentLLM()
    customer = CustomerAgent(
        memory=None, knowledge=None, llm=llm  # type: ignore[arg-type]
    )
    analyst = AnalystAgent(
        memory=None,
        redis=None,
        nl2sql=None,
        executor=None,
        llm=llm,
        cache_ttl_seconds=600,
    )  # type: ignore[arg-type]

    customer_intent = asyncio.run(customer.classify_intent("任意客服问题"))
    analyst_intent = asyncio.run(analyst.classify_intent("任意分析问题"))

    assert (customer_intent.name, customer_intent.confidence) == ("faq", 0.93)
    assert (analyst_intent.name, analyst_intent.confidence) == (
        "customer_stats",
        0.91,
    )


def test_dedicated_chat_request_can_omit_agent_type() -> None:
    request = ChatRequest(
        session_id="session-1",
        user_id="user-1",
        message="你好",
    )

    assert request.agent_type == AgentType.CUSTOMER
