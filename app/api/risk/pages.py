"""风控页面路由：落地页 + 值班台 + 联调台。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

pages_router = APIRouter(tags=["risk-demo"])

_VIEW = Path(__file__).resolve().parents[2] / "view" / "risk"
_LAB_HTML = _VIEW / "lab.html"
_INDEX_HTML = _VIEW / "index.html"
_DESK_HTML = _VIEW / "desk.html"
STATIC_DIR = _VIEW / "static"


@pages_router.get("/risk-lab", summary="风控联调台（开发）")
async def risk_lab_page() -> FileResponse:
    return FileResponse(_LAB_HTML, media_type="text/html; charset=utf-8")


@pages_router.get("/risk-demo", summary="WealthSense 演示落地页")
async def risk_demo_index() -> FileResponse:
    return FileResponse(_INDEX_HTML, media_type="text/html; charset=utf-8")


@pages_router.get("/risk-demo/desk", summary="风控值班台（OES 式工作台）")
async def risk_demo_desk() -> FileResponse:
    return FileResponse(_DESK_HTML, media_type="text/html; charset=utf-8")
