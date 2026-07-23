"""RW-013：政治公众人物（PEP）关联账户异常。

触发：PEP/PEP关联人 且（单笔≥20万 或 新增境外对手 或 模式变化>50%）
风险：高；处理优先级：1
"""

from __future__ import annotations

from decimal import Decimal

from app.tool.risk.base import BaseRiskRule, RuleHit, RuleSeverity
from app.tool.risk.context import TransactionContext

_AMOUNT_THRESHOLD = Decimal("200000")
_PATTERN_CHANGE_THRESHOLD = 0.5


class PepAbnormalRule(BaseRiskRule):
    rule_id = "RW-013"
    rule_name = "政治公众人物（PEP）关联账户异常"
    severity = RuleSeverity.HIGH
    weight = 1.5
    process_priority = 1

    def evaluate(self, context: TransactionContext) -> RuleHit | None:
        if not (context.is_pep or context.is_pep_related):
            return None

        reasons: list[str] = []
        if context.amount >= _AMOUNT_THRESHOLD:
            reasons.append(f"单笔金额={context.amount}≥{_AMOUNT_THRESHOLD}")
        if context.has_new_overseas_counterparty:
            reasons.append("新增境外交易对手方")
        if (
            context.pattern_change_ratio is not None
            and context.pattern_change_ratio > _PATTERN_CHANGE_THRESHOLD
        ):
            reasons.append(
                f"交易模式变化={context.pattern_change_ratio:.0%}"
                f">{_PATTERN_CHANGE_THRESHOLD:.0%}"
            )
        if not reasons:
            return None

        pep_tag = "PEP" if context.is_pep else "PEP关联人"
        return RuleHit(
            rule_id=self.rule_id,
            rule_name=self.rule_name,
            severity=self.severity,
            detail=f"客户标记为{pep_tag}；" + "；".join(reasons),
            weight=self.weight,
            process_priority=self.process_priority,
        )
