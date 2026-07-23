"""可更换的风控演示剧本（不绑死某一客户画像）。

用法：
- 单测 / 脚本通过 `get_scenario(name)` 取 MonitorRequest
- 换演示只改场景名，不必改业务代码
"""

from __future__ import annotations

from decimal import Decimal

from collections.abc import Callable

from app.models.schemas.risk import MonitorRequest

# 默认演示场景名；答辩前可改成任意已注册 key
DEFAULT_DEMO_SCENARIO = "sanction_country"


def scenario_sanction_country() -> MonitorRequest:
    """高优先级 RW-011：制裁/高风险地区大额往来。"""

    return MonitorRequest(
        customer_id="DEMO-SANCTION-01",
        amount=Decimal("15000"),
        currency="CNY",
        counterparty_country="IR",
        trade_type="import",
        extra={"scenario": "sanction_country", "remark": "演示高风险国家往来"},
    )


def scenario_pep_overseas() -> MonitorRequest:
    """高优先级 RW-013：PEP + 新增境外对手。"""

    return MonitorRequest(
        customer_id="DEMO-PEP-01",
        amount=Decimal("80000"),
        currency="CNY",
        is_pep=True,
        has_new_overseas_counterparty=True,
        extra={"scenario": "pep_overseas"},
    )


def scenario_multi_rule_combo() -> MonitorRequest:
    """RW-011 + RW-013 双命中，便于讲「就高」与置信度。"""

    return MonitorRequest(
        customer_id="DEMO-COMBO-01",
        amount=Decimal("250000"),
        currency="CNY",
        counterparty_country="KP",
        is_pep=True,
        has_new_overseas_counterparty=True,
        extra={"scenario": "multi_rule_combo"},
    )


def scenario_gambling_pattern() -> MonitorRequest:
    """高优先级 RW-019：涉赌涉诈三特征同时满足。"""

    return MonitorRequest(
        customer_id="DEMO-GAMBLE-01",
        amount=Decimal("50000"),
        currency="CNY",
        gambling_inbound_small=True,
        gambling_outbound_large_integer=True,
        gambling_inbound_night=True,
        extra={"scenario": "gambling_pattern"},
    )


def scenario_fund_aggregation() -> MonitorRequest:
    """优先级 2 · RW-004：分散转入集中转出。"""

    return MonitorRequest(
        customer_id="DEMO-AGG-01",
        amount=Decimal("5000"),
        currency="CNY",
        distinct_in_sources_5d=5,
        outbound_amount_5d=Decimal("200000"),
        outbound_concentration=0.85,
        extra={"scenario": "fund_aggregation"},
    )


def scenario_clean_with_audit() -> MonitorRequest:
    """无命中 + 强制审计样例（讲抽样「已检-无风险」）。"""

    return MonitorRequest(
        customer_id="DEMO-CLEAN-01",
        amount=Decimal("3000"),
        currency="CNY",
        counterparty_country="US",
        force_audit=True,
        extra={"scenario": "clean_with_audit"},
    )


SCENARIOS: dict[str, Callable[[], MonitorRequest]] = {
    "sanction_country": scenario_sanction_country,
    "pep_overseas": scenario_pep_overseas,
    "multi_rule_combo": scenario_multi_rule_combo,
    "gambling_pattern": scenario_gambling_pattern,
    "fund_aggregation": scenario_fund_aggregation,
    "clean_with_audit": scenario_clean_with_audit,
}


def list_scenario_names() -> list[str]:
    return sorted(SCENARIOS)


def get_scenario(name: str | None = None) -> MonitorRequest:
    key = name or DEFAULT_DEMO_SCENARIO
    if key not in SCENARIOS:
        known = ", ".join(list_scenario_names())
        raise KeyError(f"未知演示场景: {key}；可选: {known}")
    return SCENARIOS[key]()
