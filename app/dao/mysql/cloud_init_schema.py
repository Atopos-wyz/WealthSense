"""通过临时 SSH 隧道初始化云端 MySQL 客户画像表。

SSH 密码只从进程环境变量 ``WEALTHSENSE_SSH_PASSWORD`` 读取，不落盘。
"""

import asyncio
import os
import select
import socketserver
import threading
from contextlib import contextmanager
from collections.abc import Iterator

import paramiko
from dotenv import load_dotenv
from sqlalchemy.exc import OperationalError

from app.dao.mysql.init_schema import run


LOCAL_TUNNEL_HOST = "127.0.0.1"
LOCAL_TUNNEL_PORT = 13306
REMOTE_MYSQL_HOST = "127.0.0.1"
REMOTE_MYSQL_PORT = 3306


class _ForwardServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class _ForwardHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        transport = self.server.ssh_transport  # type: ignore[attr-defined]
        channel = transport.open_channel(
            "direct-tcpip",
            (REMOTE_MYSQL_HOST, REMOTE_MYSQL_PORT),
            self.request.getpeername(),
        )
        if channel is None:
            raise RuntimeError("SSH服务器拒绝MySQL端口转发")

        try:
            while True:
                readable, _, _ = select.select(
                    [self.request, channel],
                    [],
                    [],
                )
                if self.request in readable:
                    data = self.request.recv(65536)
                    if not data:
                        break
                    channel.sendall(data)
                if channel in readable:
                    data = channel.recv(65536)
                    if not data:
                        break
                    self.request.sendall(data)
        finally:
            channel.close()


def _split_ssh_target(host: str, configured_user: str | None) -> tuple[str, str]:
    if "@" in host:
        embedded_user, hostname = host.rsplit("@", maxsplit=1)
        return hostname, configured_user or embedded_user
    if not configured_user:
        raise RuntimeError(".env 中缺少 SSH_USER")
    return host, configured_user


@contextmanager
def cloud_mysql_tunnel() -> Iterator[int]:
    """建立云服务器到 MySQL 的临时本地端口转发。"""

    load_dotenv()
    ssh_host = os.getenv("SSH_HOST")
    if not ssh_host:
        raise RuntimeError(".env 中缺少 SSH_HOST")

    ssh_password = os.environ.pop("WEALTHSENSE_SSH_PASSWORD", None)
    if not ssh_password:
        raise RuntimeError("进程环境中缺少 WEALTHSENSE_SSH_PASSWORD")

    hostname, username = _split_ssh_target(
        ssh_host,
        os.getenv("SSH_USER"),
    )
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(
        hostname=hostname,
        username=username,
        password=ssh_password,
        look_for_keys=False,
        allow_agent=False,
        timeout=15,
        auth_timeout=15,
    )
    del ssh_password

    transport = client.get_transport()
    if transport is None or not transport.is_active():
        client.close()
        raise RuntimeError("SSH连接未激活")

    server = _ForwardServer(
        (LOCAL_TUNNEL_HOST, LOCAL_TUNNEL_PORT),
        _ForwardHandler,
    )
    server.ssh_transport = transport  # type: ignore[attr-defined]
    thread = threading.Thread(
        target=server.serve_forever,
        name="wealthsense-cloud-mysql-tunnel",
        daemon=True,
    )
    thread.start()

    try:
        print(
            "云端MySQL隧道已建立: "
            f"{LOCAL_TUNNEL_HOST}:{LOCAL_TUNNEL_PORT}"
        )
        yield LOCAL_TUNNEL_PORT
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        client.close()
        print("云端MySQL临时隧道已关闭")


def main() -> None:
    with cloud_mysql_tunnel() as port:
        use_root = False
        try:
            check_result = asyncio.run(
                run(
                    check_only=True,
                    use_root=False,
                    port_override=port,
                )
            )
        except OperationalError:
            use_root = True
            check_result = asyncio.run(
                run(
                    check_only=True,
                    use_root=True,
                    port_override=port,
                )
            )

        if check_result != 0:
            raise SystemExit(check_result)

        result = asyncio.run(
            run(
                check_only=False,
                use_root=use_root,
                port_override=port,
            )
        )
        raise SystemExit(result)


if __name__ == "__main__":
    main()
