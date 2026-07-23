"""阶段 4：可更换演示剧本 — 完整 AML 链路演通。

默认场景：sanction_country（可改为 multi_rule_combo / gambling_pattern 等）。
"""

from __future__ import annotations

import pytest

from app.dao.mysql.risk_alert_dao import InMemoryRiskAlertStore
from app.event.channels import RISK_ALERT_CHANNEL
from app.event.risk_alert_publisher import InMemoryEventPublisher
from app.service.risk.alert_service import RiskAlertService
from app.service.risk.handle_service import RiskHandleService
from app.service.risk.monitor_service import RiskMonitorService
from app.service.risk.reason_llm import ReasonLlmService
from tests.fixtures.risk_demo_scenarios import (
    DEFAULT_DEMO_SCENARIO,
    get_scenario,
    list_scenario_names,
)


@pytest.mark.parametrize("scenario_name", list_scenario_names())
@pytest.mark.asyncio
async def test_each_demo_scenario_runs(scenario_name: str) -> None:
    """每个注册场景都能跑通 monitor（命中或审计）。"""

    memory = InMemoryEventPublisher()
    store = InMemoryRiskAlertStore()
    service = RiskMonitorService(
        store=store,
        publisher=memory,
        memory_publisher=memory,
        llm=ReasonLlmService(mode="mock"),
    )
    request = get_scenario(scenario_name)
    result = await service.monitor(request)

    if scenario_name == "clean_with_audit":
        assert result.hit is False
        assert result.record_type == "audit_clean"
        assert result.broadcasted is False
        assert memory.published == []
    else:
        assert result.hit is True
        assert result.alert_level in {"低", "中", "高"}
        assert result.alert_id is not None
        assert result.reason
        assert result.llm_review
        if result.alert_level in {"中", "高"}:
            assert result.broadcasted is True
            assert memory.published
            assert memory.published[0][0] == RISK_ALERT_CHANNEL


@pytest.mark.asyncio
async def test_default_demo_story_three_minute_path() -> None:
    """默认演示：监测 → 落库 → 广播 → 查询 → 专员确认。"""

    memory = InMemoryEventPublisher()
    store = InMemoryRiskAlertStore()
    monitor = RiskMonitorService(
        store=store,
        publisher=memory,
        memory_publisher=memory,
        llm=ReasonLlmService(mode="mock"),
    )
    alerts = RiskAlertService(store)
    handle = RiskHandleService(store)

    request = get_scenario(DEFAULT_DEMO_SCENARIO)
    result = await monitor.monitor(request)

    assert result.hit is True
    assert result.alert_id is not None
    assert result.broadcasted is True
    assert result.work_order_id
    assert "RW-" in (result.reason or "")

    detail = await alerts.get_public(result.alert_id)
    assert detail["customer_id"] == request.customer_id
    assert detail["alert_level"] == result.alert_level
    assert "id_card" not in detail

    listed = await alerts.list_public(request.customer_id)
    assert any(item["alert_id"] == result.alert_id for item in listed)

    confirmed = await handle.handle(result.alert_id, "已确认")
    assert confirmed["status"] == "已确认"

    channel, payload = memory.published[0]
    assert channel == RISK_ALERT_CHANNEL
    assert payload["customer_id"] == request.customer_id
    assert payload["trigger_rules"]
