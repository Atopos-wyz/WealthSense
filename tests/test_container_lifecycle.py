import asyncio
import threading
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI

from app.config.settings import Settings
from app.config.ssh_tunnel import TunnelEndpoint
from app.container import (
    _close_external_resources,
    build_container,
)
from app.main import finish_background_task, lifespan


class _FailingRedis:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True
        raise RuntimeError("redis close failed")


class _TrackingEngine:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


class _TrackingTunnel:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class ResourceCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_close_failure_does_not_skip_remaining_resources(self) -> None:
        redis = _FailingRedis()
        engine = _TrackingEngine()
        tunnel = _TrackingTunnel()
        with self.assertRaises(RuntimeError):
            await _close_external_resources(
                redis,
                engine,
                tunnel,
                raise_errors=True,
            )
        self.assertTrue(redis.closed)
        self.assertTrue(engine.disposed)
        self.assertTrue(tunnel.closed)

    async def test_cancelled_start_waits_for_tunnel_then_closes_it(self) -> None:
        started = threading.Event()
        release = threading.Event()

        class SlowTunnel(_TrackingTunnel):
            mysql_endpoint = None
            redis_endpoint = None

            def start(self) -> None:
                started.set()
                release.wait(timeout=2)
                self.mysql_endpoint = TunnelEndpoint("127.0.0.1", 43001)
                self.redis_endpoint = TunnelEndpoint("127.0.0.1", 43002)

        tunnel = SlowTunnel()
        settings = Settings(
            _env_file=None,
            mysql_url="mysql+aiomysql://user:pass@127.0.0.1/db",
            redis_url="redis://default:pass@127.0.0.1/0",
            ssh_tunnel_enabled=True,
            ssh_host="server.example.com",
            ssh_username="ubuntu",
            ssh_password="secret",
        )
        with patch(
            "app.container.SshTunnelManager",
            return_value=tunnel,
        ):
            build_task = asyncio.create_task(build_container(settings))
            await asyncio.to_thread(started.wait, 1)
            build_task.cancel()
            await asyncio.sleep(0)
            build_task.cancel()
            await asyncio.sleep(0)
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await build_task
        self.assertTrue(tunnel.closed)


class _NoopService:
    expire_risk_reviews = AsyncMock()
    expire_confirmations = AsyncMock()
    resume_ready_operations = AsyncMock()
    reconcile_pending_operations = AsyncMock()


class _NoopPublisher:
    flush_pending = AsyncMock()


class _FailingSubscriber:
    def __init__(self) -> None:
        self.stopped = False

    async def listen(self, channels, handler) -> None:
        del channels, handler
        raise RuntimeError("redis disconnected")

    def stop(self) -> None:
        self.stopped = True


class _LifecycleContainer:
    def __init__(self) -> None:
        self.subscriber = _FailingSubscriber()
        self.operation_service = _NoopService()
        self.publisher = _NoopPublisher()
        self.event_router = AsyncMock()
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FastApiLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_background_task_timeout_is_bounded(self) -> None:
        never = asyncio.Event()

        async def ignores_first_cancel() -> None:
            try:
                await never.wait()
            except asyncio.CancelledError:
                await never.wait()

        task = asyncio.create_task(ignores_first_cancel())
        loop = asyncio.get_running_loop()
        started_at = loop.time()
        await finish_background_task(
            task,
            name="stubborn task",
            timeout=0.01,
        )
        self.assertLess(loop.time() - started_at, 0.08)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_subscriber_failure_does_not_skip_container_close(self) -> None:
        container = _LifecycleContainer()
        application = FastAPI()
        with (
            patch(
                "app.main.get_settings",
                return_value=Settings(
                    _env_file=None,
                    mysql_url=None,
                    redis_url=None,
                    ssh_tunnel_enabled=False,
                ),
            ),
            patch(
                "app.main.build_container",
                new=AsyncMock(return_value=container),
            ),
        ):
            async with lifespan(application):
                await asyncio.sleep(0)
        self.assertTrue(container.subscriber.stopped)
        self.assertTrue(container.closed)

    async def test_repeated_lifespan_cancel_still_closes_container(self) -> None:
        entered = asyncio.Event()
        close_started = asyncio.Event()
        allow_close = asyncio.Event()

        class CancelContainer(_LifecycleContainer):
            def __init__(self) -> None:
                super().__init__()
                self.subscriber = None

            async def close(self) -> None:
                close_started.set()
                await allow_close.wait()
                self.closed = True

        container = CancelContainer()
        application = FastAPI()

        async def run_lifespan() -> None:
            with (
                patch(
                    "app.main.get_settings",
                    return_value=Settings(
                        _env_file=None,
                        mysql_url=None,
                        redis_url=None,
                        ssh_tunnel_enabled=False,
                    ),
                ),
                patch(
                    "app.main.build_container",
                    new=AsyncMock(return_value=container),
                ),
            ):
                async with lifespan(application):
                    entered.set()
                    await asyncio.Event().wait()

        lifecycle_task = asyncio.create_task(run_lifespan())
        await entered.wait()
        lifecycle_task.cancel()
        await close_started.wait()
        lifecycle_task.cancel()
        allow_close.set()
        with self.assertRaises(asyncio.CancelledError):
            await lifecycle_task
        self.assertTrue(container.closed)


if __name__ == "__main__":
    unittest.main()
