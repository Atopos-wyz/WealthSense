"""黄金用例：固定输入 + 固定期望（规则命中 / 级别 / 是否广播）。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.dao.mysql.risk_alert_dao import InMemoryRiskAlertStore
from app.event.payloads import RiskAlertEvent
from app.models.schemas.risk import MonitorRequest
from app.service.risk.monitor_service import RiskMonitorService
from app.service.risk.reason_llm import (
    ALLOWED_LLM_REVIEWS,
    LLM_REVIEW_HUMAN,
    ReasonLlmService,
    _detect_conflict,
)
from tests.fixtures.risk_demo_scenarios import get_scenario


def _svc() -> RiskMonitorService:
    return RiskMonitorService(
        store=InMemoryRiskAlertStore(),
        llm=ReasonLlmService(mode="mock"),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario,expect_hit,expect_rules,expect_level,expect_broadcast",
    [
        ("sanction_country", True, {"RW-011"}, "高", True),
        ("pep_overseas", True, {"RW-013"}, "高", True),
        ("multi_rule_combo", True, {"RW-011", "RW-013"}, "高", True),
        ("gambling_pattern", True, {"RW-019"}, "高", True),
        ("fund_aggregation", True, {"RW-004"}, "高", True),
        ("clean_with_audit", False, set(), None, False),
    ],
)
async def test_demo_scenarios_golden(
    scenario: str,
    expect_hit: bool,
    expect_rules: set[str],
    expect_level: str | None,
    expect_broadcast: bool,
) -> None:
    result = await _svc().monitor(get_scenario(scenario))
    assert result.hit is expect_hit
    assert {item.rule_id for item in result.hit_rules} == expect_rules
    assert result.alert_level == expect_level
    assert result.broadcasted is expect_broadcast
    if expect_broadcast:
        assert result.work_order_id == f"WO-{result.alert_id}"
        assert result.llm_review in ALLOWED_LLM_REVIEWS
        assert result.llm_conflict is False


@pytest.mark.asyncio
async def test_rw011_boundary_amount_not_hit() -> None:
    """金额差一点点不中（9999 < 10000）。"""

    req = MonitorRequest(
        customer_id="GOLD-RW011-BOUNDARY",
        amount=Decimal("9999"),
        currency="CNY",
        counterparty_country="IR",
    )
    result = await _svc().monitor(req)
    assert result.hit is False
    assert "RW-011" not in {r.rule_id for r in result.hit_rules}


@pytest.mark.asyncio
async def test_rw013_pep_without_signal_not_hit() -> None:
    """PEP 但无金额/境外/模式变化 → 不中。"""

    req = MonitorRequest(
        customer_id="GOLD-RW013-BOUNDARY",
        amount=Decimal("1000"),
        currency="CNY",
        is_pep=True,
    )
    result = await _svc().monitor(req)
    assert result.hit is False


@pytest.mark.asyncio
async def test_rw005_must_hit() -> None:
    req = MonitorRequest(
        customer_id="GOLD-RW005",
        amount=Decimal("8000"),
        currency="CNY",
        has_large_inbound_5d=True,
        distinct_out_targets_3d=5,
        outbound_below_ctr_threshold=True,
    )
    result = await _svc().monitor(req)
    assert result.hit is True
    assert {r.rule_id for r in result.hit_rules} == {"RW-005"}
    assert result.alert_level == "高"
    assert result.broadcasted is True


@pytest.mark.asyncio
async def test_rw018_must_hit() -> None:
    req = MonitorRequest(
        customer_id="GOLD-RW018",
        amount=Decimal("10000"),
        currency="CNY",
        linked_account_count=3,
        aggregation_amount_7d=Decimal("300000"),
        funds_to_same_target=True,
    )
    result = await _svc().monitor(req)
    assert result.hit is True
    assert {r.rule_id for r in result.hit_rules} == {"RW-018"}
    assert result.broadcasted is True


@pytest.mark.asyncio
async def test_shallow_skip_full_small_clean() -> None:
    """小额 + 无核心命中 → skip_full。"""

    req = MonitorRequest(
        customer_id="GOLD-SKIP",
        amount=Decimal("3000"),
        currency="CNY",
        counterparty_country="US",
    )
    result = await _svc().monitor(req)
    assert result.hit is False
    assert result.skip_full is True
    assert result.broadcasted is False


@pytest.mark.asyncio
async def test_event_payload_appendix_a_fields() -> None:
    """中高广播事件字段对齐附录 A。"""

    svc = _svc()
    result = await svc.monitor(get_scenario("sanction_country"))
    assert result.broadcasted is True
    published = svc.memory_publisher.published
    assert published
    channel, payload = published[-1]
    assert channel == "event:risk_alert"
    event = RiskAlertEvent.model_validate(payload)
    assert event.event_type == "risk_alert"
    assert event.schema_version == "1.0"
    assert event.alert_id == result.alert_id
    assert event.alert_level == "高"
    assert event.work_order_id == result.work_order_id
    assert event.llm_conflict is False
    assert "RW-011" in event.trigger_rules


def test_llm_conflict_decision_table() -> None:
    review, conflict = _detect_conflict(
        alert_level="高",
        llm_review=LLM_REVIEW_HUMAN,
        model_says_no_risk=True,
    )
    assert conflict is True
    assert review == LLM_REVIEW_HUMAN
    review2, conflict2 = _detect_conflict(
        alert_level="高",
        llm_review="同意规则",
        model_says_no_risk=False,
    )
    assert conflict2 is False
    assert review2 == "同意规则"
