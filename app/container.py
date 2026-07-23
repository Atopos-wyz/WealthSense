import asyncio
import logging
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
from app.dao.mysql.mock_business_repository import (
    SqlAlchemyMockBusinessRepository,
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
from app.tool.operation.database_registry import DatabaseOperationToolRegistry
from app.tool.operation.registry import OperationTool, OperationToolRegistry

logger = logging.getLogger(__name__)


async def _wait_for_task_ignoring_cancellation(
    task: asyncio.Task,
) -> bool:
    was_cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            was_cancelled = True
    return was_cancelled


async def _start_ssh_tunnel(tunnel: SshTunnelManager) -> None:
    start_task = asyncio.create_task(asyncio.to_thread(tunnel.start))
    was_cancelled = await _wait_for_task_ignoring_cancellation(start_task)
    if start_task.cancelled():
        raise asyncio.CancelledError
    start_task.result()
    if was_cancelled:
        raise asyncio.CancelledError


async def _close_external_resources(
    redis: Redis | None,
    engine: AsyncEngine | None,
    ssh_tunnel: SshTunnelManager | None,
    *,
    raise_errors: bool,
) -> None:
    errors: list[BaseException] = []
    if redis:
        try:
            await redis.aclose()
        except BaseException as exc:
            errors.append(exc)
            logger.exception("failed to close Redis client")
    if engine:
        try:
            await engine.dispose()
        except BaseException as exc:
            errors.append(exc)
            logger.exception("failed to dispose SQLAlchemy engine")
    if ssh_tunnel:
        try:
            await asyncio.to_thread(ssh_tunnel.close)
        except BaseException as exc:
            errors.append(exc)
            logger.exception("failed to close SSH tunnel")
    if errors and raise_errors:
        raise RuntimeError(
            f"{len(errors)} infrastructure resource(s) failed to close"
        ) from errors[0]


@dataclass(slots=True)
class AppContainer:
    settings: Settings
    repository: OperationRepository
    state_store: StateStore
    publisher: EventPublisher
    tool_registry: OperationTool
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
        await _close_external_resources(
            self.redis,
            self.engine,
            self.ssh_tunnel,
            raise_errors=True,
        )


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
                await _start_ssh_tunnel(ssh_tunnel)
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
            mock_business_repository = SqlAlchemyMockBusinessRepository(
                session_factory
            )
            tool_registry: OperationTool = DatabaseOperationToolRegistry(
                mock_business_repository
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
            tool_registry = OperationToolRegistry()

        publisher: EventPublisher = DurableEventPublisher(repository, transport)
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
    except BaseException as original_error:
        cleanup_task = asyncio.create_task(
            _close_external_resources(
                redis,
                engine,
                ssh_tunnel,
                raise_errors=False,
            )
        )
        cancelled_during_cleanup = (
            await _wait_for_task_ignoring_cancellation(cleanup_task)
        )
        if not cleanup_task.cancelled():
            cleanup_task.result()
        if (
            cancelled_during_cleanup
            and not isinstance(original_error, asyncio.CancelledError)
        ):
            raise asyncio.CancelledError from original_error
        raise
