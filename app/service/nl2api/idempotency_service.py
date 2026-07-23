from app.dao.redis.state_store import StateStore
from app.utils.exceptions import OperatorConflictError as ConflictError


class IdempotencyService:
    def __init__(self, store: StateStore, ttl_seconds: int) -> None:
        self.store = store
        self.ttl_seconds = ttl_seconds

    async def acquire(self, operation_id: str, version: int) -> str:
        key = f"operator:idempotency:{operation_id}:{version}"
        is_acquired = await self.store.acquire_lock(key, self.ttl_seconds)
        if not is_acquired:
            raise ConflictError(
                "OP_DUPLICATE_REQUEST",
                "操作正在执行或已经执行",
            )
        return key
