"""风控 API 包。

AML 监测路由始终可用；问卷评估路由在依赖齐全时由 main 单独挂载。
"""

from app.api.risk.monitor_router import router

__all__ = ["router"]
