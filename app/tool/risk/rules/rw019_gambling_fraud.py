"""RW-019：疑似涉赌/涉诈资金流转。

触发：同时满足 ①小额入金 ②大额整数出金 ③夜间入金集中
风险：高；处理优先级：1
"""

from __future__ import annotations

from app.tool.risk.base import BaseRiskRule, RuleHit, RuleSeverity
from app.tool.risk.context import TransactionContext


class GamblingFraudPatternRule(BaseRiskRule):
    rule_id = "RW-019"
    rule_name = "疑似涉赌/涉诈资金流转"
    severity = RuleSeverity.HIGH
    weight = 1.6
    process_priority = 1

    def evaluate(self, context: TransactionContext) -> RuleHit | None:
        if not (
            context.gambling_inbound_small
            and context.gambling_outbound_large_integer
            and context.gambling_inbound_night
        ):
            return None
        return RuleHit(
            rule_id=self.rule_id,
            rule_name=self.rule_name,
            severity=self.severity,
            detail=(
                "同时满足：①入金小额特征；②出金大额整数特征；"
                "③入金集中在20:00-02:00"
            ),
            weight=self.weight,
            process_priority=self.process_priority,
        )
