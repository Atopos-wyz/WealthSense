"""兼容画像缓存的 Redis 客户端入口。"""

from redis.asyncio import Redis

from app.dao import get_database_manager


def get_redis_client() -> Redis | None:
    manager = get_database_manager()
    if not manager.redis.connected:
        return None
    return manager.redis.client
