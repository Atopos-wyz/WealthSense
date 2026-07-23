"""为仅监听服务器回环地址的数据库建立本地 SSH 端口转发。"""

from __future__ import annotations

import argparse
import getpass
import os
import select
import socket
import socketserver
import threading
from dataclasses import dataclass

import paramiko


@dataclass(frozen=True, slots=True)
class Forward:
    local_port: int
    remote_port: int


DEFAULT_FORWARDS = (
    Forward(13306, 3306),
    Forward(16379, 6379),
    Forward(17687, 7687),
    Forward(19530, 19530),
)


class _ForwardHandler(socketserver.BaseRequestHandler):
    transport: paramiko.Transport
    remote_port: int

    def handle(self) -> None:
        channel = self.transport.open_channel(
            "direct-tcpip",
            ("127.0.0.1", self.remote_port),
            self.request.getpeername(),
        )
        if channel is None:
            return
        try:
            while True:
                readable, _, _ = select.select([self.request, channel], [], [])
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


class _ThreadingServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def _build_server(
    transport: paramiko.Transport,
    forward: Forward,
) -> _ThreadingServer:
    handler = type(
        f"ForwardHandler{forward.local_port}",
        (_ForwardHandler,),
        {"transport": transport, "remote_port": forward.remote_port},
    )
    return _ThreadingServer(("127.0.0.1", forward.local_port), handler)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="114.132.213.216")
    parser.add_argument("--user", default="ubuntu")
    parser.add_argument("--ssh-port", type=int, default=22)
    args = parser.parse_args()

    password = os.getenv("WEALTHSENSE_SSH_PASSWORD") or getpass.getpass(
        f"{args.user}@{args.host} password: "
    )
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        args.host,
        port=args.ssh_port,
        username=args.user,
        password=password,
        timeout=10,
    )
    transport = client.get_transport()
    if transport is None:
        raise RuntimeError("SSH transport initialization failed")

    servers = [_build_server(transport, forward) for forward in DEFAULT_FORWARDS]
    threads = [
        threading.Thread(target=server.serve_forever, daemon=True)
        for server in servers
    ]
    for thread in threads:
        thread.start()

    mappings = ", ".join(
        f"127.0.0.1:{forward.local_port}->127.0.0.1:{forward.remote_port}"
        for forward in DEFAULT_FORWARDS
    )
    print(f"SSH tunnel ready: {mappings}")
    try:
        while transport.is_active():
            threading.Event().wait(1)
    except KeyboardInterrupt:
        pass
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        client.close()


if __name__ == "__main__":
    main()
