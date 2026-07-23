from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.operator.agent import BusinessOperatorAgent
from app.config.database import create_engine, create_session_factory, create_tables
from app.config.redis import create_redis_client
from app.config.settings import Settings
from app.dao.mysql.operation_repository import (
    InMemoryOperationRepository,
    OperationRepository,
    SqlAlchemyOperationRepository,
)
from app.dao.redis.event_publisher import (
    DurableEventPublisher,
    EventPublisher,
    InMemoryEventPublisher,
    RedisEventPublisher,
)
from app.dao.redis.event_subscriber import RedisEventSubscriber
from app.dao.redis.state_store import (
    InMemoryStateStore,
    RedisStateStore,
    StateStore,
)
from app.event.event_router import OperatorEventRouter
from app.service.nl2api.operation_service import OperationService
from app.tool.operation.registry import OperationToolRegistry


@dataclass(slots=True)
class AppContainer:
    settings: Settings
    repository: OperationRepository
    state_store: StateStore
    publisher: EventPublisher
    tool_registry: OperationToolRegistry
    operation_service: OperationService
    operator_agent: BusinessOperatorAgent
    event_router: OperatorEventRouter
    redis: Redis | None = None
    subscriber: RedisEventSubscriber | None = None
    engine: AsyncEngine | None = None

    async def close(self) -> None:
        if self.subscriber:
            self.subscriber.stop()
        if self.redis:
            await self.redis.aclose()
        if self.engine:
            await self.engine.dispose()


async def build_container(settings: Settings) -> AppContainer:
    redis: Redis | None = None
    subscriber: RedisEventSubscriber | None = None
    engine: AsyncEngine | None = None

    if bool(settings.mysql_url) != bool(settings.redis_url):
        raise RuntimeError(
            "WEALTHSENSE_MYSQL_URL and WEALTHSENSE_REDIS_URL "
            "must be configured together"
        )
    if settings.is_production:
        secrets = [settings.jwt_secret, *settings.event_hmac_secrets.values()]
        if any(secret.startswith("dev-") or "change-me" in secret for secret in secrets):
            raise RuntimeError(
                "production requires non-default JWT and per-Agent event secrets"
            )

    if settings.has_external_infrastructure:
        engine = create_engine(settings.mysql_url or "")
        await create_tables(engine)
        session_factory = create_session_factory(engine)
        repository: OperationRepository = SqlAlchemyOperationRepository(
            session_factory
        )
        redis = create_redis_client(settings.redis_url or "")
        state_store: StateStore = RedisStateStore(redis)
        transport: EventPublisher = RedisEventPublisher(
            redis,
            settings.event_hmac_secrets,
            settings.event_stream_key,
        )
        subscriber = RedisEventSubscriber(redis, settings.event_hmac_secrets)
    else:
        if settings.is_production:
            raise RuntimeError(
                "production requires both WEALTHSENSE_MYSQL_URL and "
                "WEALTHSENSE_REDIS_URL"
            )
        repository = InMemoryOperationRepository()
        state_store = InMemoryStateStore()
        transport = InMemoryEventPublisher(settings.event_hmac_secrets)

    publisher: EventPublisher = DurableEventPublisher(repository, transport)

    tool_registry = OperationToolRegistry()
    operation_service = OperationService(
        repository,
        state_store,
        publisher,
        tool_registry,
        risk_review_ttl_seconds=settings.risk_review_ttl_seconds,
        confirmation_ttl_seconds=settings.confirmation_ttl_seconds,
        idempotency_ttl_seconds=settings.idempotency_ttl_seconds,
        jwt_secret=settings.jwt_secret,
        jwt_issuer=settings.jwt_issuer,
    )
    operator_agent = BusinessOperatorAgent(operation_service)
    event_router = OperatorEventRouter(operation_service)
    return AppContainer(
        settings=settings,
        repository=repository,
        state_store=state_store,
        publisher=publisher,
        tool_registry=tool_registry,
        operation_service=operation_service,
        operator_agent=operator_agent,
        event_router=event_router,
        redis=redis,
        subscriber=subscriber,
        engine=engine,
    )
