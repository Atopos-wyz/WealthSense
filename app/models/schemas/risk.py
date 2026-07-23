"""风控监测模块请求/响应 Schema。"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import Field

from app.models.schemas.response import PublicSchema


class MonitorRequest(PublicSchema):
    """交易监测入参。窗口类字段由调用方预聚合传入。"""

    customer_id: str = Field(min_length=1, description="客户标识")
    amount: Decimal = Field(ge=0, description="本笔交易金额（人民币）")
    currency: str = Field(default="CNY", min_length=1)
    counterparty_country: str | None = Field(
        default=None,
        description="对手方国家/地区（ISO 或中文名）",
    )
    trade_type: str | None = Field(default=None, description="交易类型，可选")

    is_pep: bool = False
    is_pep_related: bool = False
    has_new_overseas_counterparty: bool = False
    pattern_change_ratio: float | None = Field(
        default=None,
        description="交易模式相对近3月变化比例，如 0.6 表示 60%",
    )

    distinct_in_sources_5d: int | None = Field(
        default=None, description="近5日不同转入来源账户数"
    )
    outbound_amount_5d: Decimal | None = Field(
        default=None, description="近5日转出金额合计"
    )
    outbound_concentration: float | None = Field(
        default=None, description="转出对手方集中度 0~1"
    )

    has_large_inbound_5d: bool = Field(
        default=False, description="近5日是否有单笔≥10万转入"
    )
    distinct_out_targets_3d: int | None = Field(
        default=None, description="随后3日分散转出对手账户数"
    )
    outbound_below_ctr_threshold: bool = Field(
        default=False,
        description="分散转出单笔是否均低于大额转账报告标准（20万）",
    )

    linked_account_count: int | None = Field(
        default=None, description="证件/手机/设备关联账户数"
    )
    aggregation_amount_7d: Decimal | None = Field(
        default=None, description="7日归集至同一目标金额"
    )
    funds_to_same_target: bool = False

    gambling_inbound_small: bool = Field(
        default=False, description="RW-019① 小额入金特征"
    )
    gambling_outbound_large_integer: bool = Field(
        default=False, description="RW-019② 大额整数出金特征"
    )
    gambling_inbound_night: bool = Field(
        default=False, description="RW-019③ 20:00-02:00 入金集中"
    )

    force_audit: bool = Field(
        default=False,
        description="无命中时强制写「已检-无风险」审计样例（演示用）",
    )
    extra: dict[str, Any] = Field(default_factory=dict)


class HitRuleItem(PublicSchema):
    rule_id: str
    rule_name: str
    severity: str
    detail: str


class MonitorResponse(PublicSchema):
    customer_id: str
    hit: bool
    alert_level: str | None = None
    hit_rules: list[HitRuleItem] = Field(default_factory=list)
    reason: str | None = None
    confidence: float = Field(ge=0, le=1)
    skip_full: bool = False
    alert_id: int | None = None
    llm_review: str | None = None
    llm_source: str | None = None
    record_type: str | None = None
    status: str | None = None
    work_order_id: str | None = None
    broadcasted: bool = False
    redis_published: bool = Field(
        default=False,
        description="是否成功 PUBLISH 到 Redis（内存总线成功不等于 Redis 成功）",
    )
    redis_error: str | None = Field(
        default=None,
        description="Redis 发布失败原因（若有）",
    )


class HandleAlertRequest(PublicSchema):
    status: Literal["未处理", "已确认", "已排除"]


class AlertView(PublicSchema):
    alert_id: int
    customer_id: str
    record_type: str
    alert_level: str | None = None
    hit_rules: list[Any] = Field(default_factory=list)
    reason: str | None = None
    confidence: float
    llm_review: str | None = None
    status: str
    work_order_id: str | None = None
    broadcasted: bool
    created_at: str
