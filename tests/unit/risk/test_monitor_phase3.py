"""阶段 3：落库矩阵、广播、LLM、查询与处置权限。"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.risk import router as risk_router
from app.config.settings import Settings, get_settings
from app.dao.mysql.risk_alert_dao import InMemoryRiskAlertStore
from app.event.channels import RISK_ALERT_CHANNEL
from app.event.publisher import InMemoryEventPublisher
from app.models.schemas.auth import UserRole
from app.models.schemas.risk import MonitorRequest
from app.service.risk.access_policy import scrub_extra
from app.service.risk.monitor_service import RiskMonitorService
from app.service.risk.reason_llm import ReasonLlmService
from app.utils.exception_handlers import register_exception_handlers
from app.utils.permissions import create_access_token


def build_settings(**overrides) -> Settings:
    values = {
        "mysql_password": "mysql-secret",
        "redis_password": "redis-secret",
        "neo4j_password": "neo4j-secret",
        "milvus_root_password": "milvus-secret",
        "jwt_secret_key": "test-jwt-secret-with-enough-entropy",
        "app_env": "development",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def settings() -> Settings:
    return build_settings()


@pytest.mark.asyncio
async def test_hit_persists_and_broadcasts_mid_high() -> None:
    memory = InMemoryEventPublisher()
    store = InMemoryRiskAlertStore()
    service = RiskMonitorService(
        store=store,
        publisher=memory,
        memory_publisher=memory,
        llm=ReasonLlmService(mode="mock"),
    )
    result = await service.monitor(
        MonitorRequest(
            customer_id="c-hit",
            amount=Decimal("20000"),
            counterparty_country="IR",
        )
    )
    assert result.hit is True
    assert result.alert_id is not None
    assert result.broadcasted is True
    assert result.work_order_id == f"WO-{result.alert_id}"
    assert result.llm_review in {"可疑", "建议人工复核", "正常倾向"}
    assert "RW-011" in (result.reason or "")

    saved = await store.get(result.alert_id)
    assert saved is not None
    assert saved.broadcasted is True
    assert len(memory.published) == 1
    channel, payload = memory.published[0]
    assert channel == RISK_ALERT_CHANNEL
    assert payload["alert_id"] == result.alert_id
    assert payload["alert_level"] == "高"
    assert "RW-011" in payload["trigger_rules"]


@pytest.mark.asyncio
async def test_no_hit_force_audit_writes_clean_record_without_broadcast() -> None:
    memory = InMemoryEventPublisher()
    store = InMemoryRiskAlertStore()
    service = RiskMonitorService(
        store=store,
        publisher=memory,
        memory_publisher=memory,
    )
    result = await service.monitor(
        MonitorRequest(
            customer_id="c-clean",
            amount=Decimal("1000"),
            counterparty_country="US",
            force_audit=True,
        )
    )
    assert result.hit is False
    assert result.alert_id is not None
    assert result.record_type == "audit_clean"
    assert result.broadcasted is False
    assert memory.published == []
    saved = await store.get(result.alert_id)
    assert saved is not None
    assert saved.reason == "已检-无风险"


@pytest.mark.asyncio
async def test_llm_off_falls_back_to_template() -> None:
    service = RiskMonitorService(llm=ReasonLlmService(mode="off"))
    result = await service.monitor(
        MonitorRequest(
            customer_id="c-llm",
            amount=Decimal("20000"),
            counterparty_country="KP",
        )
    )
    assert result.llm_source == "template"
    assert result.llm_review == "未启用"
    assert "RW-011" in (result.reason or "")


def test_scrub_sensitive_extra() -> None:
    cleaned = scrub_extra(
        {"remark": "ok", "id_card": "3301...", "持仓": [1, 2], "note": "x"}
    )
    assert cleaned == {"remark": "ok", "note": "x"}


def test_alert_query_and_handle_api(settings: Settings) -> None:
    app = FastAPI()
    register_exception_handlers(app)
    app.dependency_overrides[get_settings] = lambda: settings
    app.include_router(risk_router)
    client = TestClient(app)

    risk_token = create_access_token(
        subject="risk-1",
        roles=[UserRole.RISK_OFFICER],
        settings=settings,
    )
    customer_token = create_access_token(
        subject="c1",
        roles=[UserRole.CUSTOMER],
        settings=settings,
    )

    monitor = client.post(
        "/api/risk/monitor",
        headers={"Authorization": f"Bearer {risk_token}"},
        json={
            "customer_id": "C-API",
            "amount": "20000",
            "counterparty_country": "IR",
        },
    )
    assert monitor.status_code == 200
    alert_id = monitor.json()["data"]["alert_id"]

    listed = client.get(
        "/api/risk/alerts",
        params={"customer_id": "C-API"},
        headers={"Authorization": f"Bearer {risk_token}"},
    )
    assert listed.status_code == 200
    assert listed.json()["data"][0]["alert_id"] == alert_id
    assert "id_card" not in listed.json()["data"][0]

    forbidden = client.get(
        "/api/risk/alerts",
        params={"customer_id": "C-API"},
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert forbidden.status_code == 403

    handled = client.post(
        f"/api/risk/alerts/{alert_id}/handle",
        headers={"Authorization": f"Bearer {risk_token}"},
        json={"status": "已确认"},
    )
    assert handled.status_code == 200
    assert handled.json()["data"]["status"] == "已确认"

    events = client.get(
        "/api/risk/dev/last-events",
        headers={"Authorization": f"Bearer {risk_token}"},
    )
    assert events.status_code == 200
    assert len(events.json()["data"]) >= 1

    token_resp = client.post("/api/risk/dev/token")
    assert token_resp.status_code == 200
    assert token_resp.json()["data"]["token"]
