"""动态 Schema NL2SQL 生成与只读执行。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from sqlalchemy import text

from app.dao.mysql import MySQLConnectionManager
from app.service.llm import LanguageModelClient
from app.tool.sql.safety import SQLSafetyTool


class AnalystIntent(str, Enum):
    HOLDINGS_QUERY = "holdings_query"
    RETURN_STATS = "return_stats"
    TRANSACTION_QUERY = "transaction_query"
    CUSTOMER_STATS = "customer_stats"
    PRODUCT_STATS = "product_stats"
    WORKORDER_QUERY = "workorder_query"


TABLES_BY_INTENT: dict[AnalystIntent, tuple[str, ...]] = {
    AnalystIntent.HOLDINGS_QUERY: ("fin_holdings", "fin_product", "sys_user"),
    AnalystIntent.RETURN_STATS: (
        "fin_holdings",
        "fin_product",
        "fin_transaction",
    ),
    AnalystIntent.TRANSACTION_QUERY: ("fin_transaction", "fin_product"),
    AnalystIntent.CUSTOMER_STATS: (
        "sys_user",
        "fin_customer_profile",
        "fin_holdings",
    ),
    AnalystIntent.PRODUCT_STATS: ("fin_product",),
    AnalystIntent.WORKORDER_QUERY: ("biz_work_order", "sys_user"),
}

FEW_SHOTS: dict[AnalystIntent, tuple[tuple[str, str], ...]] = {
    AnalystIntent.HOLDINGS_QUERY: (
        (
            "客户10001目前持有哪些产品？",
            "SELECT p.product_name, h.shares, h.current_value "
            "FROM fin_holdings h JOIN fin_product p ON h.product_id=p.id "
            "WHERE h.customer_id=10001 LIMIT 100",
        ),
    ),
    AnalystIntent.RETURN_STATS: (
        (
            "各产品类型的平均预期收益率是多少？",
            "SELECT product_type, AVG(expected_return) AS average_return "
            "FROM fin_product GROUP BY product_type LIMIT 100",
        ),
    ),
    AnalystIntent.TRANSACTION_QUERY: (
        (
            "客户10001最近一个月的交易记录",
            "SELECT * FROM fin_transaction WHERE customer_id=10001 "
            "AND create_time>=DATE_SUB(CURRENT_DATE, INTERVAL 1 MONTH) LIMIT 100",
        ),
    ),
    AnalystIntent.CUSTOMER_STATS: (
        (
            "AUM超过100万的客户有多少个？",
            "SELECT COUNT(*) AS customer_count FROM fin_customer_profile "
            "WHERE total_assets>1000000 LIMIT 100",
        ),
    ),
    AnalystIntent.PRODUCT_STATS: (
        (
            "各类型产品数量",
            "SELECT product_type, COUNT(*) AS product_count FROM fin_product "
            "GROUP BY product_type LIMIT 100",
        ),
    ),
    AnalystIntent.WORKORDER_QUERY: (
        (
            "查看待处理工单",
            "SELECT * FROM biz_work_order WHERE status='待处理' LIMIT 100",
        ),
    ),
}


class SQLSchemaProvider:
    def __init__(self, mysql: MySQLConnectionManager) -> None:
        self._mysql = mysql

    async def schema_for(self, intent: AnalystIntent) -> str:
        await self._mysql.connect()
        definitions: list[str] = []
        async with self._mysql.engine.connect() as connection:
            database_name = (
                await connection.execute(text("SELECT DATABASE()"))
            ).scalar_one()
            for table in TABLES_BY_INTENT[intent]:
                exists = (
                    await connection.execute(
                        text(
                            "SELECT COUNT(*) FROM information_schema.TABLES "
                            "WHERE TABLE_SCHEMA=:schema AND TABLE_NAME=:table"
                        ),
                        {
                            "schema": database_name,
                            "table": table,
                        },
                    )
                ).scalar_one()
                if not exists:
                    continue
                row = (
                    await connection.execute(text(f"SHOW CREATE TABLE `{table}`"))
                ).one()
                definitions.append(str(row[1]))
        return "\n\n".join(definitions)

    @staticmethod
    def few_shots_for(intent: AnalystIntent) -> str:
        return "\n".join(
            f"问题：{question}\nSQL：{sql}"
            for question, sql in FEW_SHOTS[intent]
        )


class NL2SQLTool:
    def __init__(
        self,
        *,
        llm: LanguageModelClient,
        schema_provider: SQLSchemaProvider,
    ) -> None:
        self._llm = llm
        self._schema_provider = schema_provider

    @staticmethod
    def classify_intent(message: str) -> tuple[AnalystIntent, float]:
        rules = (
            (AnalystIntent.HOLDINGS_QUERY, ("持仓", "持有", "有哪些产品")),
            (AnalystIntent.RETURN_STATS, ("收益", "收益率", "回报")),
            (AnalystIntent.TRANSACTION_QUERY, ("交易记录", "最近交易", "转账记录")),
            (AnalystIntent.CUSTOMER_STATS, ("多少客户", "客户数", "aum", "资产超过")),
            (AnalystIntent.PRODUCT_STATS, ("产品总数", "产品数量", "在售产品", "各类型")),
            (AnalystIntent.WORKORDER_QUERY, ("工单", "待处理")),
        )
        lowered = message.lower()
        for intent, keywords in rules:
            if any(keyword in lowered for keyword in keywords):
                return intent, 0.9
        return AnalystIntent.PRODUCT_STATS, 0.55

    async def generate(
        self,
        message: str,
        intent: AnalystIntent,
    ) -> tuple[str, str]:
        schema = await self._schema_provider.schema_for(intent)
        if self._llm.available:
            system = (
                "你是金融数据分析 SQL 专家。根据给定 MySQL 8.0 Schema "
                "只生成一条 SELECT 查询，不要输出解释或 Markdown。"
                "禁止任何写操作，结果最多100行，日期使用 CURRENT_DATE。\n\n"
                f"Schema:\n{schema}\n\n"
                f"Few-shot:\n{self._schema_provider.few_shots_for(intent)}"
            )
            try:
                raw = await self._llm.chat(
                    system=system,
                    user=message,
                    temperature=0,
                )
                return self._strip_sql_fence(raw), schema
            except Exception:
                pass
        return self._template_sql(message, intent), schema

    @staticmethod
    def _strip_sql_fence(raw: str) -> str:
        value = raw.strip()
        value = re.sub(r"^```(?:sql)?\s*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s*```$", "", value)
        return value.strip()

    @staticmethod
    def _template_sql(message: str, intent: AnalystIntent) -> str:
        customer_match = re.search(
            r"客户(?:ID)?\s*[:：#]?\s*(\d+)",
            message,
            re.IGNORECASE,
        )
        customer_id = int(customer_match.group(1)) if customer_match else None

        if intent == AnalystIntent.CUSTOMER_STATS:
            amount_match = re.search(r"(\d+(?:\.\d+)?)\s*(万|亿)?", message)
            amount = float(amount_match.group(1)) if amount_match else 100
            unit = amount_match.group(2) if amount_match else "万"
            multiplier = 10000 if unit == "万" else 100000000 if unit == "亿" else 1
            threshold = int(amount * multiplier)
            return (
                "SELECT COUNT(*) AS customer_count FROM fin_customer_profile "
                f"WHERE total_assets > {threshold}"
            )
        if intent == AnalystIntent.HOLDINGS_QUERY:
            where = f" WHERE h.customer_id = {customer_id}" if customer_id else ""
            return (
                "SELECT h.customer_id, p.product_name, h.shares, "
                "h.current_value, h.profit_loss FROM fin_holdings h "
                "JOIN fin_product p ON h.product_id = p.id"
                f"{where} ORDER BY h.current_value DESC"
            )
        if intent == AnalystIntent.RETURN_STATS:
            return (
                "SELECT product_type, AVG(expected_return) AS average_return "
                "FROM fin_product GROUP BY product_type ORDER BY product_type"
            )
        if intent == AnalystIntent.TRANSACTION_QUERY:
            where = (
                f"customer_id = {customer_id} AND " if customer_id else ""
            )
            return (
                "SELECT * FROM fin_transaction WHERE "
                f"{where}create_time >= DATE_SUB(CURRENT_DATE, INTERVAL 1 MONTH) "
                "ORDER BY create_time DESC"
            )
        if intent == AnalystIntent.WORKORDER_QUERY:
            return (
                "SELECT * FROM biz_work_order WHERE status = '待处理' "
                "ORDER BY create_time DESC"
            )
        if "在售" in message:
            return (
                "SELECT id, product_code, product_name, product_type, "
                "risk_level, expected_return FROM fin_product "
                "WHERE status = '在售' ORDER BY id"
            )
        return (
            "SELECT product_type, COUNT(*) AS product_count FROM fin_product "
            "GROUP BY product_type ORDER BY product_type"
        )


@dataclass(frozen=True, slots=True)
class SQLExecutionResult:
    sql: str
    rows: list[dict[str, Any]]


class SQLExecutor:
    def __init__(
        self,
        *,
        mysql: MySQLConnectionManager,
        safety: SQLSafetyTool,
    ) -> None:
        self._mysql = mysql
        self._safety = safety

    async def execute(self, sql: str) -> SQLExecutionResult:
        prepared = self._safety.prepare(sql)
        await self._mysql.connect()
        async with self._mysql.engine.connect() as connection:
            result = await connection.execute(text(prepared))
            rows = [dict(row) for row in result.mappings().all()]
        return SQLExecutionResult(sql=prepared, rows=rows)
