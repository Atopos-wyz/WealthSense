"""RW-004：分散转入集中转出。

触发：5日内≥5个不同来源转入 且 转出≥20万 且 对手集中度≥80%
风险：高；处理优先级：2
"""

from __future__ import annotations

from decimal import Decimal

from app.tool.risk.base import BaseRiskRule, RuleHit, RuleSeverity
from app.tool.risk.context import TransactionContext

_MIN_SOURCES = 5
_OUTBOUND_THRESHOLD = Decimal("200000")
_CONCENTRATION_THRESHOLD = 0.8


class DisperseInConcentrateOutRule(BaseRiskRule):
    rule_id = "RW-004"
    rule_name = "分散转入集中转出"
    severity = RuleSeverity.HIGH
    weight = 1.4
    process_priority = 2

    def evaluate(self, context: TransactionContext) -> RuleHit | None:
        sources = context.distinct_in_sources_5d
        outbound = context.outbound_amount_5d
        concentration = context.outbound_concentration
        if sources is None or outbound is None or concentration is None:
            return None
        if sources < _MIN_SOURCES:
            return None
        if outbound < _OUTBOUND_THRESHOLD:
            return None
        if concentration < _CONCENTRATION_THRESHOLD:
            return None
        return RuleHit(
            rule_id=self.rule_id,
            rule_name=self.rule_name,
            severity=self.severity,
            detail=(
                f"5日不同转入来源={sources}≥{_MIN_SOURCES}，"
                f"转出金额={outbound}≥{_OUTBOUND_THRESHOLD}，"
                f"转出集中度={concentration:.0%}≥{_CONCENTRATION_THRESHOLD:.0%}"
            ),
            weight=self.weight,
            process_priority=self.process_priority,
        )
