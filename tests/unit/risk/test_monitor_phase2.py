"""阶段 2：优先级 1～2 规则 + 浅/深检门控 + confidence。"""

from __future__ import annotations

from decimal import Decimal

from app.models.schemas.risk import MonitorRequest
from app.service.risk.engine import SHALLOW_AMOUNT_THRESHOLD, RiskRuleEngine
from app.service.risk.grader import compute_confidence
from app.service.risk.monitor_service import RiskMonitorService
from app.tool.risk.context import TransactionContext
from app.tool.risk.rules.rw004_disperse_in_concentrate_out import (
    DisperseInConcentrateOutRule,
)
from app.tool.risk.rules.rw005_concentrate_in_disperse_out import (
    ConcentrateInDisperseOutRule,
)
from app.tool.risk.rules.rw013_pep_abnormal import PepAbnormalRule
from app.tool.risk.rules.rw018_multi_account_aggregation import (
    MultiAccountAggregationRule,
)
from app.tool.risk.rules.rw019_gambling_fraud import GamblingFraudPatternRule


def test_rw013_pep_large_amount() -> None:
    hit = PepAbnormalRule().evaluate(
        TransactionContext(
            customer_id="p1",
            amount=Decimal("200000"),
            is_pep=True,
        )
    )
    assert hit is not None
    assert hit.rule_id == "RW-013"


def test_rw013_pep_without_abnormal_misses() -> None:
    hit = PepAbnormalRule().evaluate(
        TransactionContext(
            customer_id="p1",
            amount=Decimal("10000"),
            is_pep=True,
        )
    )
    assert hit is None


def test_rw018_aggregation_hit() -> None:
    hit = MultiAccountAggregationRule().evaluate(
        TransactionContext(
            customer_id="a1",
            amount=Decimal("1"),
            linked_account_count=3,
            aggregation_amount_7d=Decimal("300000"),
            funds_to_same_target=True,
        )
    )
    assert hit is not None
    assert hit.rule_id == "RW-018"


def test_rw019_requires_all_three_features() -> None:
    rule = GamblingFraudPatternRule()
    assert (
        rule.evaluate(
            TransactionContext(
                customer_id="g1",
                amount=Decimal("1"),
                gambling_inbound_small=True,
                gambling_outbound_large_integer=True,
                gambling_inbound_night=False,
            )
        )
        is None
    )
    hit = rule.evaluate(
        TransactionContext(
            customer_id="g1",
            amount=Decimal("1"),
            gambling_inbound_small=True,
            gambling_outbound_large_integer=True,
            gambling_inbound_night=True,
        )
    )
    assert hit is not None
    assert hit.rule_id == "RW-019"


def test_rw004_and_rw005() -> None:
    hit4 = DisperseInConcentrateOutRule().evaluate(
        TransactionContext(
            customer_id="c1",
            amount=Decimal("1"),
            distinct_in_sources_5d=5,
            outbound_amount_5d=Decimal("200000"),
            outbound_concentration=0.8,
        )
    )
    assert hit4 is not None
    assert hit4.rule_id == "RW-004"

    hit5 = ConcentrateInDisperseOutRule().evaluate(
        TransactionContext(
            customer_id="c1",
            amount=Decimal("1"),
            has_large_inbound_5d=True,
            distinct_out_targets_3d=5,
            outbound_below_ctr_threshold=True,
        )
    )
    assert hit5 is not None
    assert hit5.rule_id == "RW-005"


def test_shallow_gate_skips_when_small_amount_and_no_core_hit() -> None:
    result = RiskRuleEngine().evaluate_with_gate(
        TransactionContext(
            customer_id="n1",
            amount=SHALLOW_AMOUNT_THRESHOLD - Decimal("1"),
            counterparty_country="US",
        )
    )
    assert result.hits == []
    assert result.skip_full is True
    assert compute_confidence(hits=[], skip_full=True) == 0.90


def test_monitor_multi_hit_and_confidence() -> None:
    import asyncio

    service = RiskMonitorService()
    result = asyncio.run(
        service.monitor(
            MonitorRequest(
                customer_id="multi-1",
                amount=Decimal("250000"),
                counterparty_country="IR",
                is_pep=True,
                has_new_overseas_counterparty=True,
            )
        )
    )
    rule_ids = {item.rule_id for item in result.hit_rules}
    assert "RW-011" in rule_ids
    assert "RW-013" in rule_ids
    assert result.hit is True
    assert result.alert_level == "高"
    assert result.confidence >= 0.55
    assert result.skip_full is False


def test_monitor_no_hit_includes_confidence() -> None:
    import asyncio

    service = RiskMonitorService()
    result = asyncio.run(
        service.monitor(
            MonitorRequest(
                customer_id="ok-1",
                amount=Decimal("1000"),
                counterparty_country="US",
            )
        )
    )
    assert result.hit is False
    assert result.confidence == 0.90
    assert result.skip_full is True
