"""风险规则注册表。"""

from __future__ import annotations

from app.tool.risk.base import BaseRiskRule


class RuleRegistry:
    def __init__(self) -> None:
        self._rules: dict[str, BaseRiskRule] = {}

    def register(self, rule: BaseRiskRule) -> None:
        self._rules[rule.rule_id] = rule

    def get(self, rule_id: str) -> BaseRiskRule | None:
        return self._rules.get(rule_id)

    def all_rules(self) -> list[BaseRiskRule]:
        return sorted(
            self._rules.values(),
            key=lambda rule: (rule.process_priority, rule.rule_id),
        )

    def rules_by_max_priority(self, max_priority: int) -> list[BaseRiskRule]:
        return [
            rule
            for rule in self.all_rules()
            if rule.process_priority <= max_priority
        ]

    def rules_above_priority(self, min_priority_exclusive: int) -> list[BaseRiskRule]:
        return [
            rule
            for rule in self.all_rules()
            if rule.process_priority > min_priority_exclusive
        ]


def build_default_registry() -> RuleRegistry:
    """阶段 2：注册原文优先级 1～2 规则。"""

    from app.tool.risk.rules.rw004_disperse_in_concentrate_out import (
        DisperseInConcentrateOutRule,
    )
    from app.tool.risk.rules.rw005_concentrate_in_disperse_out import (
        ConcentrateInDisperseOutRule,
    )
    from app.tool.risk.rules.rw011_high_risk_country import HighRiskCountryRule
    from app.tool.risk.rules.rw013_pep_abnormal import PepAbnormalRule
    from app.tool.risk.rules.rw018_multi_account_aggregation import (
        MultiAccountAggregationRule,
    )
    from app.tool.risk.rules.rw019_gambling_fraud import GamblingFraudPatternRule

    registry = RuleRegistry()
    for rule in (
        HighRiskCountryRule(),
        PepAbnormalRule(),
        MultiAccountAggregationRule(),
        GamblingFraudPatternRule(),
        DisperseInConcentrateOutRule(),
        ConcentrateInDisperseOutRule(),
    ):
        registry.register(rule)
    return registry
