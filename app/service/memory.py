"""Redis 短期会话记忆与 MySQL 会话归档。"""

from __future__ import annotations

import json
import asyncio
from datetime import datetime, timezone

from app.dao.mysql import ConversationRepository
from app.dao.mysql import MySQLConnectionManager
from app.dao.redis import RedisConnectionManager
from app.models.schemas.chat import SessionMessage
from app.service.bootstrap import create_required_tables


class SessionMemoryService:
    def __init__(
        self,
        *,
        redis: RedisConnectionManager,
        archive: ConversationRepository,
        mysql: MySQLConnectionManager,
        ttl_seconds: int,
        max_messages: int,
        token_budget: int,
    ) -> None:
        self._redis = redis
        self._archive = archive
        self._mysql = mysql
        self._ttl_seconds = ttl_seconds
        self._max_messages = max_messages
        self._token_budget = token_budget
        self._initialized = False
        self._initialize_lock = asyncio.Lock()

    async def recall(self, session_id: str) -> list[SessionMessage]:
        await self._initialize()
        try:
            await self._redis.connect()
            values = await self._redis.client.lrange(
                self._message_key(session_id),
                0,
                -1,
            )
            return [SessionMessage.model_validate_json(value) for value in values]
        except Exception:
            archived = await self._archive.history(
                session_id,
                limit=self._max_messages,
            )
            return [
                SessionMessage(
                    role=item.role,
                    content=item.content,
                    timestamp=item.create_time.replace(
                        tzinfo=timezone.utc
                    ).isoformat(),
                )
                for item in archived
            ]

    async def append_exchange(
        self,
        *,
        session_id: str,
        user_id: str,
        agent_type: str,
        user_message: str,
        assistant_message: str,
        response_metadata: dict,
    ) -> None:
        await self._initialize()
        now = datetime.now(timezone.utc).isoformat()
        messages = [
            SessionMessage(role="user", content=user_message, timestamp=now),
            SessionMessage(role="assistant", content=assistant_message, timestamp=now),
        ]
        try:
            await self._redis.connect()
            client = self._redis.client
            life_key = f"session:{session_id}:lifetime"
            await client.set(life_key, "1", nx=True, ex=86400)
            lifetime_ttl = await client.ttl(life_key)
            ttl = min(self._ttl_seconds, max(1, lifetime_ttl))
            message_key = self._message_key(session_id)
            async with client.pipeline(transaction=True) as pipeline:
                pipeline.rpush(
                    message_key,
                    *(message.model_dump_json() for message in messages),
                )
                pipeline.ltrim(message_key, -self._max_messages, -1)
                pipeline.expire(message_key, ttl)
                await pipeline.execute()
            await self._trim_to_budget(message_key)
        except Exception:
            pass

        await self._archive.archive(
            session_id=session_id,
            user_id=user_id,
            agent_type=agent_type,
            role="user",
            content=user_message,
        )
        await self._archive.archive(
            session_id=session_id,
            user_id=user_id,
            agent_type=agent_type,
            role="assistant",
            content=assistant_message,
            extra_data=response_metadata,
        )

    async def _trim_to_budget(self, message_key: str) -> None:
        values = await self._redis.client.lrange(message_key, 0, -1)
        parsed = [json.loads(value) for value in values]
        estimated = sum(self._estimate_tokens(item.get("content", "")) for item in parsed)
        remove_count = 0
        while estimated > self._token_budget and remove_count < len(parsed) - 2:
            estimated -= self._estimate_tokens(parsed[remove_count].get("content", ""))
            remove_count += 1
        if remove_count:
            await self._redis.client.ltrim(message_key, remove_count, -1)

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        ascii_count = sum(character.isascii() for character in text)
        non_ascii_count = len(text) - ascii_count
        return max(1, non_ascii_count + (ascii_count + 3) // 4)

    @staticmethod
    def _message_key(session_id: str) -> str:
        return f"session:{session_id}:messages"

    async def _initialize(self) -> None:
        if self._initialized:
            return
        async with self._initialize_lock:
            if not self._initialized:
                await create_required_tables(self._mysql)
                self._initialized = True
