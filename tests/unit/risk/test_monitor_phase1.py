"""阶段 1：RW-011 规则引擎与 monitor 接口。"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.risk import router as risk_router
from app.config.settings import Settings, get_settings
from app.models.schemas.auth import UserRole
from app.models.schemas.risk import MonitorRequest
from app.service.risk.engine import RiskRuleEngine
from app.service.risk.monitor_service import RiskMonitorService
from app.tool.risk.context import TransactionContext
from app.tool.risk.rules.rw011_high_risk_country import HighRiskCountryRule
from app.utils.exception_handlers import register_exception_handlers
from app.utils.permissions import create_access_token


def build_settings(**overrides) -> Settings:
    values = {
        "mysql_password": "mysql-secret",
        "redis_password": "redis-secret",
        "neo4j_password": "neo4j-secret",
        "milvus_root_password": "milvus-secret",
        "jwt_secret_key": "test-jwt-secret-with-enough-entropy",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def settings() -> Settings:
    return build_settings()


def test_rw011_hits_when_sanctioned_country_and_amount_ge_10000() -> None:
    rule = HighRiskCountryRule()
    hit = rule.evaluate(
        TransactionContext(
            customer_id="c1",
            amount=Decimal("10000"),
            counterparty_country="伊朗",
        )
    )
    assert hit is not None
    assert hit.rule_id == "RW-011"
    assert hit.severity.value == "高"


def test_rw011_misses_when_amount_below_threshold() -> None:
    rule = HighRiskCountryRule()
    hit = rule.evaluate(
        TransactionContext(
            customer_id="c1",
            amount=Decimal("9999.99"),
            counterparty_country="IR",
        )
    )
    assert hit is None


def test_rw011_misses_when_country_not_listed() -> None:
    rule = HighRiskCountryRule()
    hit = rule.evaluate(
        TransactionContext(
            customer_id="c1",
            amount=Decimal("50000"),
            counterparty_country="CN",
        )
    )
    assert hit is None


@pytest.mark.asyncio
async def test_monitor_service_returns_hit_and_template_reason() -> None:
    service = RiskMonitorService(RiskRuleEngine())
    result = await service.monitor(
        MonitorRequest(
            customer_id="demo-001",
            amount=Decimal("15000"),
            counterparty_country="KP",
        )
    )
    assert result.hit is True
    assert result.alert_level == "高"
    assert result.hit_rules[0].rule_id == "RW-011"
    assert result.reason is not None
    assert "RW-011" in result.reason
    assert result.confidence >= 0.55
    assert result.skip_full is False
    assert result.alert_id is not None
    assert result.broadcasted is True
    assert result.llm_review is not None


@pytest.mark.asyncio
async def test_monitor_service_returns_no_hit() -> None:
    service = RiskMonitorService(RiskRuleEngine())
    result = await service.monitor(
        MonitorRequest(
            customer_id="demo-001",
            amount=Decimal("15000"),
            counterparty_country="US",
        )
    )
    assert result.hit is False
    assert result.alert_level is None
    assert result.hit_rules == []
    assert result.confidence > 0
    assert result.skip_full is True
    assert result.broadcasted is False


def test_monitor_api_requires_risk_read_and_returns_envelope(settings: Settings) -> None:
    app = FastAPI()
    register_exception_handlers(app)
    app.dependency_overrides[get_settings] = lambda: settings
    app.include_router(risk_router)
    client = TestClient(app)

    token = create_access_token(
        subject="risk-1",
        roles=[UserRole.RISK_OFFICER],
        settings=settings,
    )
    response = client.post(
        "/api/risk/monitor",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "customer_id": "demo-001",
            "amount": "20000",
            "counterparty_country": "叙利亚",
        },
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["code"] == 200
    assert payload["data"]["hit"] is True
    assert payload["data"]["alert_level"] == "高"
    assert payload["data"]["hit_rules"][0]["rule_id"] == "RW-011"
    assert payload["data"]["broadcasted"] is True


def test_monitor_api_forbidden_without_risk_permission(settings: Settings) -> None:
    app = FastAPI()
    register_exception_handlers(app)
    app.dependency_overrides[get_settings] = lambda: settings
    app.include_router(risk_router)
    client = TestClient(app)

    token = create_access_token(
        subject="customer-1",
        roles=[UserRole.CUSTOMER],
        settings=settings,
    )
    response = client.post(
        "/api/risk/monitor",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "customer_id": "demo-001",
            "amount": "20000",
            "counterparty_country": "IR",
        },
    )
    assert response.status_code == 403
    assert response.json()["code"] == 403
