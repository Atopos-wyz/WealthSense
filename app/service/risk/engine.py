"""风控规则引擎（支持浅检/深检门控）。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.tool.risk.base import BaseRiskRule, RuleHit
from app.tool.risk.context import TransactionContext
from app.tool.risk.registry import RuleRegistry, build_default_registry

# 浅检：先跑原文优先级 1～2；未命中且金额低于该阈值则跳过其余规则
CORE_MAX_PRIORITY = 2
SHALLOW_AMOUNT_THRESHOLD = Decimal("50000")


@dataclass(frozen=True, slots=True)
class EngineResult:
    hits: list[RuleHit]
    skip_full: bool


class RiskRuleEngine:
    def __init__(self, registry: RuleRegistry | None = None) -> None:
        self._registry = registry or build_default_registry()

    def evaluate_all(self, context: TransactionContext) -> list[RuleHit]:
        return self.evaluate_with_gate(context).hits

    def evaluate_with_gate(self, context: TransactionContext) -> EngineResult:
        core_hits = self._run(self._registry.rules_by_max_priority(CORE_MAX_PRIORITY), context)
        if core_hits:
            # 核心命中后跑全量已注册规则（避免重复已跑过的）
            rest = self._registry.rules_above_priority(CORE_MAX_PRIORITY)
            rest_hits = self._run(rest, context)
            return EngineResult(hits=core_hits + rest_hits, skip_full=False)

        if context.amount < SHALLOW_AMOUNT_THRESHOLD:
            return EngineResult(hits=[], skip_full=True)

        rest = self._registry.rules_above_priority(CORE_MAX_PRIORITY)
        return EngineResult(hits=self._run(rest, context), skip_full=False)

    @staticmethod
    def _run(rules: list[BaseRiskRule], context: TransactionContext) -> list[RuleHit]:
        hits: list[RuleHit] = []
        for rule in rules:
            hit = rule.evaluate(context)
            if hit is not None:
                hits.append(hit)
        return hits
