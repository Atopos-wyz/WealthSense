from __future__ import annotations

import logging
import socketserver
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import paramiko
from sqlalchemy.engine import make_url

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TunnelEndpoint:
    host: str
    port: int


class SshTunnelError(RuntimeError):
    """Raised when a verified SSH tunnel cannot be established."""


class _ForwardServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        transport: paramiko.Transport,
        remote_address: tuple[str, int],
    ) -> None:
        self.transport = transport
        self.remote_address = remote_address
        super().__init__(server_address, _ForwardHandler)


class _ForwardHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        server = self.server
        if not isinstance(server, _ForwardServer):
            return
        try:
            channel = server.transport.open_channel(
                "direct-tcpip",
                server.remote_address,
                self.request.getpeername(),
                timeout=10,
            )
        except Exception:
            logger.exception(
                "SSH forwarding channel failed for remote endpoint %s:%s",
                *server.remote_address,
            )
            return
        if channel is None:
            return

        def remote_to_local() -> None:
            try:
                while data := channel.recv(65536):
                    self.request.sendall(data)
            except OSError:
                pass
            finally:
                try:
                    self.request.shutdown(1)
                except OSError:
                    pass

        response_thread = threading.Thread(
            target=remote_to_local,
            name="wealthsense-ssh-forward-response",
            daemon=True,
        )
        response_thread.start()
        try:
            while data := self.request.recv(65536):
                channel.sendall(data)
        except OSError:
            pass
        finally:
            channel.close()
            response_thread.join(timeout=1)


class SshTunnelManager:
    """Owns one verified SSH connection and its local TCP forwards."""

    def __init__(
        self,
        *,
        ssh_host: str,
        ssh_port: int,
        ssh_username: str,
        ssh_password: str,
        known_hosts: str,
        mysql_remote_host: str,
        mysql_remote_port: int,
        redis_remote_host: str,
        redis_remote_port: int,
        keepalive_seconds: int = 30,
    ) -> None:
        self._ssh_host = ssh_host
        self._ssh_port = ssh_port
        self._ssh_username = ssh_username
        self._ssh_password = ssh_password
        self._known_hosts = Path(known_hosts).expanduser()
        self._mysql_remote = (mysql_remote_host, mysql_remote_port)
        self._redis_remote = (redis_remote_host, redis_remote_port)
        self._keepalive_seconds = keepalive_seconds
        self._client: paramiko.SSHClient | None = None
        self._servers: list[_ForwardServer] = []
        self._threads: list[threading.Thread] = []
        self.mysql_endpoint: TunnelEndpoint | None = None
        self.redis_endpoint: TunnelEndpoint | None = None

    def start(self) -> None:
        if self._client is not None:
            raise SshTunnelError("SSH tunnel is already started")
        client = paramiko.SSHClient()
        try:
            if not self._known_hosts.is_file():
                raise SshTunnelError(
                    f"SSH known_hosts file does not exist: {self._known_hosts}"
                )
            client.load_host_keys(str(self._known_hosts))
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
            client.connect(
                hostname=self._ssh_host,
                port=self._ssh_port,
                username=self._ssh_username,
                password=self._ssh_password,
                look_for_keys=False,
                allow_agent=False,
                timeout=10,
                auth_timeout=10,
                banner_timeout=10,
            )
            transport = client.get_transport()
            if transport is None or not transport.is_active():
                raise SshTunnelError("SSH transport did not become active")
            transport.set_keepalive(self._keepalive_seconds)
            mysql_server, mysql_thread = self._start_forward(
                transport,
                self._mysql_remote,
                "mysql",
            )
            self._servers.append(mysql_server)
            self._threads.append(mysql_thread)
            redis_server, redis_thread = self._start_forward(
                transport,
                self._redis_remote,
                "redis",
            )
            self._servers.append(redis_server)
            self._threads.append(redis_thread)
            self._client = client
            self.mysql_endpoint = TunnelEndpoint(
                host="127.0.0.1",
                port=int(mysql_server.server_address[1]),
            )
            self.redis_endpoint = TunnelEndpoint(
                host="127.0.0.1",
                port=int(redis_server.server_address[1]),
            )
        except Exception as exc:
            for server in reversed(self._servers):
                server.shutdown()
                server.server_close()
            for thread in self._threads:
                thread.join(timeout=2)
            client.close()
            self._servers.clear()
            self._threads.clear()
            self.mysql_endpoint = None
            self.redis_endpoint = None
            if isinstance(exc, SshTunnelError):
                raise
            raise SshTunnelError(
                f"Unable to establish SSH tunnel to "
                f"{self._ssh_host}:{self._ssh_port}"
            ) from exc

    def _start_forward(
        self,
        transport: paramiko.Transport,
        remote_address: tuple[str, int],
        service_name: str,
    ) -> tuple[_ForwardServer, threading.Thread]:
        server = _ForwardServer(("127.0.0.1", 0), transport, remote_address)
        thread = threading.Thread(
            target=server.serve_forever,
            name=f"wealthsense-ssh-{service_name}",
            daemon=True,
        )
        thread.start()
        return server, thread

    def close(self) -> None:
        servers, threads = self._servers, self._threads
        self._servers = []
        self._threads = []
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=2)
        if self._client is not None:
            self._client.close()
            self._client = None
        self.mysql_endpoint = None
        self.redis_endpoint = None


def rewrite_mysql_url(url: str, endpoint: TunnelEndpoint) -> str:
    return make_url(url).set(
        host=endpoint.host,
        port=endpoint.port,
    ).render_as_string(hide_password=False)


def rewrite_redis_url(url: str, endpoint: TunnelEndpoint) -> str:
    parsed = urlsplit(url)
    user_info = ""
    if "@" in parsed.netloc:
        user_info = parsed.netloc.rsplit("@", 1)[0] + "@"
    host = endpoint.host
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return urlunsplit(
        (
            parsed.scheme,
            f"{user_info}{host}:{endpoint.port}",
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
    )
