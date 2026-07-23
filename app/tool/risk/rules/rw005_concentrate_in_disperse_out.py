"""RW-005：集中转入分散转出。

触发：5日内有单笔≥10万转入 且 随后3日向≥5账户分散转出
     且单笔转出低于大额转账报告标准（20万）
风险：高；处理优先级：2
"""

from __future__ import annotations

from app.tool.risk.base import BaseRiskRule, RuleHit, RuleSeverity
from app.tool.risk.context import TransactionContext

_MIN_OUT_TARGETS = 5


class ConcentrateInDisperseOutRule(BaseRiskRule):
    rule_id = "RW-005"
    rule_name = "集中转入分散转出"
    severity = RuleSeverity.HIGH
    weight = 1.4
    process_priority = 2

    def evaluate(self, context: TransactionContext) -> RuleHit | None:
        targets = context.distinct_out_targets_3d
        if not context.has_large_inbound_5d:
            return None
        if targets is None or targets < _MIN_OUT_TARGETS:
            return None
        if not context.outbound_below_ctr_threshold:
            return None
        return RuleHit(
            rule_id=self.rule_id,
            rule_name=self.rule_name,
            severity=self.severity,
            detail=(
                f"近5日存在单笔≥10万转入，随后3日向{targets}个账户分散转出"
                f"（≥{_MIN_OUT_TARGETS}），且单笔低于大额转账报告标准"
            ),
            weight=self.weight,
            process_priority=self.process_priority,
        )
