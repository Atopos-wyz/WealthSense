"""演示用：将 Redis Pub/Sub 转发为 SSE（非 production 免鉴权）。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse

from app.config.settings import Settings, get_settings
from app.dao.redis.connection import RedisConnectionManager
from app.event.channels import RISK_ALERT_CHANNEL
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/risk", tags=["risk-demo"])


@router.get(
    "/dev/subscribe-stream",
    summary="[演示] SSE 订阅 event:risk_alert（非 production 免鉴权）",
    response_model=None,
)
async def subscribe_stream(
    settings: Settings = Depends(get_settings),
):
    if settings.app_env == "production":
        return JSONResponse(
            status_code=404,
            content={"detail": "生产环境禁用订阅流"},
        )

    async def event_generator() -> AsyncIterator[str]:
        redis_mgr = RedisConnectionManager(settings)
        pubsub = None
        try:
            await redis_mgr.connect()
            pubsub = redis_mgr.client.pubsub()
            await pubsub.subscribe(RISK_ALERT_CHANNEL)
            yield (
                "event: status\n"
                f"data: {json.dumps({'state': 'subscribed', 'channel': RISK_ALERT_CHANNEL}, ensure_ascii=False)}\n\n"
            )
            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if message is None:
                    yield ": keepalive\n\n"
                    await asyncio.sleep(0.05)
                    continue
                if message.get("type") != "message":
                    continue
                payload = message.get("data")
                if isinstance(payload, (dict, list)):
                    data = json.dumps(payload, ensure_ascii=False)
                else:
                    data = str(payload)
                yield f"event: risk_alert\ndata: {data}\n\n"
        except asyncio.CancelledError:
            logger.info("SSE 订阅连接已取消")
            raise
        except Exception as exc:
            logger.warning("SSE 订阅异常: %s", exc, exc_info=True)
            yield (
                "event: error\n"
                f"data: {json.dumps({'message': str(exc)}, ensure_ascii=False)}\n\n"
            )
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(RISK_ALERT_CHANNEL)
                    await pubsub.aclose()
                except Exception:
                    logger.debug("SSE pubsub 关闭失败", exc_info=True)
            try:
                await redis_mgr.close()
            except Exception:
                logger.debug("SSE redis 关闭失败", exc_info=True)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
