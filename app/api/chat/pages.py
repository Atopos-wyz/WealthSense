"""客户与员工共用的投顾门户页面。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse


pages_router = APIRouter(tags=["advisor-portal"])

_PORTAL_HTML = (
    Path(__file__).resolve().parents[2]
    / "view"
    / "advisor"
    / "portal.html"
)


@pages_router.get("/advisor", summary="客户与员工投顾门户")
async def advisor_portal_page() -> FileResponse:
    return FileResponse(
        _PORTAL_HTML,
        media_type="text/html; charset=utf-8",
    )
