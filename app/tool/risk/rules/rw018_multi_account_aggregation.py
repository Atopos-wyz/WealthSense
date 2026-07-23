"""RW-018：多账户关联资金归集。

触发：关联≥3账户 且 7日内集中转入同一目标 且 归集金额≥30万
风险：高；处理优先级：1
"""

from __future__ import annotations

from decimal import Decimal

from app.tool.risk.base import BaseRiskRule, RuleHit, RuleSeverity
from app.tool.risk.context import TransactionContext

_MIN_LINKED_ACCOUNTS = 3
_AMOUNT_THRESHOLD = Decimal("300000")


class MultiAccountAggregationRule(BaseRiskRule):
    rule_id = "RW-018"
    rule_name = "多账户关联资金归集"
    severity = RuleSeverity.HIGH
    weight = 1.5
    process_priority = 1

    def evaluate(self, context: TransactionContext) -> RuleHit | None:
        linked = context.linked_account_count
        agg = context.aggregation_amount_7d
        if linked is None or agg is None:
            return None
        if linked < _MIN_LINKED_ACCOUNTS:
            return None
        if not context.funds_to_same_target:
            return None
        if agg < _AMOUNT_THRESHOLD:
            return None
        return RuleHit(
            rule_id=self.rule_id,
            rule_name=self.rule_name,
            severity=self.severity,
            detail=(
                f"关联账户数={linked}≥{_MIN_LINKED_ACCOUNTS}，"
                f"7日归集金额={agg}≥{_AMOUNT_THRESHOLD}，"
                "资金集中转入同一目标账户"
            ),
            weight=self.weight,
            process_priority=self.process_priority,
        )
