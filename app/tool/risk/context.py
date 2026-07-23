"""交易监测上下文（规则引擎输入）。

窗口聚合字段由调用方/后续 DAO 预计算后传入；阶段 2 不查库。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass(slots=True)
class TransactionContext:
    customer_id: str
    amount: Decimal
    currency: str = "CNY"
    counterparty_country: str | None = None
    trade_type: str | None = None

    # RW-013 PEP
    is_pep: bool = False
    is_pep_related: bool = False
    has_new_overseas_counterparty: bool = False
    pattern_change_ratio: float | None = None

    # RW-004 分散转入集中转出（5 日窗口预聚合）
    distinct_in_sources_5d: int | None = None
    outbound_amount_5d: Decimal | None = None
    outbound_concentration: float | None = None

    # RW-005 集中转入分散转出
    has_large_inbound_5d: bool = False
    distinct_out_targets_3d: int | None = None
    outbound_below_ctr_threshold: bool = False

    # RW-018 多账户关联资金归集
    linked_account_count: int | None = None
    aggregation_amount_7d: Decimal | None = None
    funds_to_same_target: bool = False

    # RW-019 涉赌涉诈三特征（预判标记，可由流水统计得出）
    gambling_inbound_small: bool = False
    gambling_outbound_large_integer: bool = False
    gambling_inbound_night: bool = False

    extra: dict[str, Any] = field(default_factory=dict)
