"""RW-011：涉及高风险国家/地区的资金往来。

规则源：《反洗钱可疑交易识别规则》JR-AML-RULE-2024-001
触发：对手方在 FATF 黑/灰名单或 OFAC 制裁国，且金额 ≥ 10,000 元
风险：高；原文处理优先级：1（最高）
"""

from __future__ import annotations

from decimal import Decimal

from app.tool.risk.base import BaseRiskRule, RuleHit, RuleSeverity
from app.tool.risk.context import TransactionContext

# Mock 名单（答辩可述「对接公开名单的占位」；不接真实 Jumio/人行接口）
_AMOUNT_THRESHOLD = Decimal("10000")

_SANCTION_OR_FATF_CODES: frozenset[str] = frozenset(
    {
        "IR",  # 伊朗
        "KP",  # 朝鲜
        "SY",  # 叙利亚
        "CU",  # 古巴（OFAC 常见示例）
        "SD",  # 苏丹
        "MM",  # 缅甸（灰名单常见示例）
        "YE",  # 也门
        "SS",  # 南苏丹
    }
)

_COUNTRY_ALIASES: dict[str, str] = {
    "伊朗": "IR",
    "朝鲜": "KP",
    "叙利亚": "SY",
    "古巴": "CU",
    "苏丹": "SD",
    "缅甸": "MM",
    "也门": "YE",
    "南苏丹": "SS",
    "IRAN": "IR",
    "NORTH KOREA": "KP",
    "SYRIA": "SY",
}


def normalize_country(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    upper = text.upper()
    if upper in _SANCTION_OR_FATF_CODES:
        return upper
    alias = _COUNTRY_ALIASES.get(text) or _COUNTRY_ALIASES.get(upper)
    if alias:
        return alias
    return upper


class HighRiskCountryRule(BaseRiskRule):
    rule_id = "RW-011"
    rule_name = "涉及高风险国家/地区的资金往来"
    severity = RuleSeverity.HIGH
    weight = 1.5
    process_priority = 1

    def evaluate(self, context: TransactionContext) -> RuleHit | None:
        code = normalize_country(context.counterparty_country)
        if code is None or code not in _SANCTION_OR_FATF_CODES:
            return None
        if context.amount < _AMOUNT_THRESHOLD:
            return None
        return RuleHit(
            rule_id=self.rule_id,
            rule_name=self.rule_name,
            severity=self.severity,
            detail=(
                f"对手方国家/地区={context.counterparty_country}({code})，"
                f"金额={context.amount}≥{_AMOUNT_THRESHOLD}"
            ),
            weight=self.weight,
            process_priority=self.process_priority,
        )
