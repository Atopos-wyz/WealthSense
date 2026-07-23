"""风控规则基类与命中结果。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from app.tool.risk.context import TransactionContext


class RuleSeverity(str, Enum):
    """对应《反洗钱可疑交易识别规则》风险色标。"""

    HIGH = "高"
    MEDIUM_HIGH = "中高"
    MEDIUM = "中"
    LOW = "低"


# API 对外统一：低 / 中 / 高（中高映射为中）
_SEVERITY_TO_ALERT: dict[RuleSeverity, str] = {
    RuleSeverity.HIGH: "高",
    RuleSeverity.MEDIUM_HIGH: "中",
    RuleSeverity.MEDIUM: "中",
    RuleSeverity.LOW: "低",
}

_ALERT_RANK: dict[str, int] = {"低": 1, "中": 2, "高": 3}


def severity_to_alert_level(severity: RuleSeverity) -> str:
    return _SEVERITY_TO_ALERT[severity]


def max_alert_level(levels: list[str]) -> str | None:
    if not levels:
        return None
    return max(levels, key=lambda level: _ALERT_RANK.get(level, 0))


@dataclass(frozen=True, slots=True)
class RuleHit:
    rule_id: str
    rule_name: str
    severity: RuleSeverity
    detail: str
    weight: float = 1.0
    process_priority: int = 5

    @property
    def alert_level(self) -> str:
        return severity_to_alert_level(self.severity)


class BaseRiskRule(ABC):
    """策略模式：每条 RW 实现 evaluate。"""

    rule_id: str
    rule_name: str
    severity: RuleSeverity
    weight: float = 1.0
    process_priority: int = 5

    @abstractmethod
    def evaluate(self, context: TransactionContext) -> RuleHit | None:
        """命中返回 RuleHit，未命中返回 None。"""
