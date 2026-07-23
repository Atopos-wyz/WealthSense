"""联调台页面可被正确挂载。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_risk_lab_page_returns_html() -> None:
    client = TestClient(app)
    response = client.get("/risk-lab")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "风控联调台" in response.text
    assert "/api/risk/monitor" in response.text
