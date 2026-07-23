"""单独订阅 Redis 风控广播，用于联调自证。

用法（另开一个终端，先于 monitor 启动）：

  python -m scripts.subscribe_risk_alert

频道：event:risk_alert
说明：redis-cli 可能把中文显示成 \\xe9\\xab\\x98；本脚本会按 UTF-8 JSON 美化打印。
"""

from __future__ import annotations

import asyncio
import json
import sys

from app.config.settings import get_settings
from app.dao.redis.connection import RedisConnectionManager
from app.event.channels import RISK_ALERT_CHANNEL


def _pretty(data: object) -> str:
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    if not isinstance(data, str):
        return str(data)
    try:
        return json.dumps(json.loads(data), ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        return data


async def main() -> int:
    settings = get_settings()
    redis = RedisConnectionManager(settings)
    try:
        await redis.connect()
    except Exception as exc:
        print(f"无法连接 Redis: {exc}", file=sys.stderr)
        print(
            "请确认 .env 中 REDIS_HOST/PORT/PASSWORD 正确，且 Redis 已启动。",
            file=sys.stderr,
        )
        return 1

    pubsub = redis.client.pubsub()
    await pubsub.subscribe(RISK_ALERT_CHANNEL)
    print(f"已订阅 {RISK_ALERT_CHANNEL}，等待风控广播…（Ctrl+C 退出）")
    print(f"连接: {settings.redis_host}:{settings.redis_port} db={settings.redis_db}")

    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            channel = message.get("channel")
            print("---")
            print(f"channel={channel}")
            print(_pretty(message.get("data")))
    except KeyboardInterrupt:
        print("\n已停止订阅")
    finally:
        await pubsub.unsubscribe(RISK_ALERT_CHANNEL)
        await pubsub.aclose()
        await redis.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
