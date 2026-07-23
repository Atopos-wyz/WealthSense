"""风控联调台页面路由（非 /api，仅服务于本地测试）。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

pages_router = APIRouter(tags=["risk-lab"])

_LAB_HTML = Path(__file__).resolve().parents[2] / "view" / "risk" / "lab.html"


@pages_router.get("/risk-lab", summary="风控联调台页面")
async def risk_lab_page() -> FileResponse:
    return FileResponse(
        _LAB_HTML,
        media_type="text/html; charset=utf-8",
    )
