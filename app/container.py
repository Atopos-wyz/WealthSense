import asyncio
from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.operator.agent import BusinessOperatorAgent
from app.config.database import create_engine, create_session_factory, create_tables
from app.config.redis import create_redis_client
from app.config.settings import Settings
from app.config.ssh_tunnel import (
    SshTunnelManager,
    rewrite_mysql_url,
    rewrite_redis_url,
)
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
    ssh_tunnel: SshTunnelManager | None = None

    async def close(self) -> None:
        if self.subscriber:
            self.subscriber.stop()
        if self.redis:
            await self.redis.aclose()
        if self.engine:
            await self.engine.dispose()
        if self.ssh_tunnel:
            await asyncio.to_thread(self.ssh_tunnel.close)


async def build_container(settings: Settings) -> AppContainer:
    redis: Redis | None = None
    subscriber: RedisEventSubscriber | None = None
    engine: AsyncEngine | None = None
    ssh_tunnel: SshTunnelManager | None = None

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

    try:
        if settings.has_external_infrastructure:
            if not settings.mysql_url or not settings.redis_url:
                raise RuntimeError("external infrastructure URLs are unavailable")
            mysql_url = settings.mysql_url.get_secret_value()
            redis_url = settings.redis_url.get_secret_value()
            if settings.ssh_tunnel_enabled:
                if not (
                    settings.ssh_host
                    and settings.ssh_username
                    and settings.ssh_password
                ):
                    raise RuntimeError("incomplete SSH tunnel configuration")
                ssh_tunnel = SshTunnelManager(
                    ssh_host=settings.ssh_host,
                    ssh_port=settings.ssh_port,
                    ssh_username=settings.ssh_username,
                    ssh_password=settings.ssh_password.get_secret_value(),
                    known_hosts=settings.ssh_known_hosts,
                    mysql_remote_host=settings.ssh_remote_mysql_host,
                    mysql_remote_port=settings.ssh_remote_mysql_port,
                    redis_remote_host=settings.ssh_remote_redis_host,
                    redis_remote_port=settings.ssh_remote_redis_port,
                    keepalive_seconds=settings.ssh_keepalive_seconds,
                )
                await asyncio.to_thread(ssh_tunnel.start)
                if not (
                    ssh_tunnel.mysql_endpoint and ssh_tunnel.redis_endpoint
                ):
                    raise RuntimeError("SSH tunnel endpoints are unavailable")
                mysql_url = rewrite_mysql_url(
                    mysql_url,
                    ssh_tunnel.mysql_endpoint,
                )
                redis_url = rewrite_redis_url(
                    redis_url,
                    ssh_tunnel.redis_endpoint,
                )

            engine = create_engine(mysql_url)
            await create_tables(engine)
            session_factory = create_session_factory(engine)
            repository: OperationRepository = SqlAlchemyOperationRepository(
                session_factory
            )
            redis = create_redis_client(redis_url)
            await redis.ping()
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
    except Exception:
        if redis:
            await redis.aclose()
        if engine:
            await engine.dispose()
        if ssh_tunnel:
            await asyncio.to_thread(ssh_tunnel.close)
        raise

    try:
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
            ssh_tunnel=ssh_tunnel,
        )
    except Exception:
        if redis:
            await redis.aclose()
        if engine:
            await engine.dispose()
        if ssh_tunnel:
            await asyncio.to_thread(ssh_tunnel.close)
        raise
