"""Redis 异步客户端。"""

from functools import lru_cache

from redis.asyncio import Redis

from app.config.settings import get_settings


@lru_cache(maxsize=1)
def get_redis_client() -> Redis | None:
    redis_url = get_settings().redis_url
    if not redis_url:
        return None
    return Redis.from_url(redis_url, decode_responses=True)
