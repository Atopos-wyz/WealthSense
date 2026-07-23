#!/usr/bin/env python3
"""SSH 隧道管理脚本 — 一键启动/管理所有数据库隧道"""
import subprocess, sys, os, signal, time
from pathlib import Path

SSH_HOST = "ubuntu@114.132.213.216"

TUNNELS = [
    ("MySQL",  13306, 3306),
    ("Redis",  6379, 6379),
    ("Neo4j HTTP", 7474, 7474),
    ("Neo4j Bolt", 7687, 7687),
    ("Milvus", 19530, 19530),
    ("Milvus Mgmt", 9091, 9091),
    ("MinIO API", 9000, 9000),
    ("MinIO Console", 9001, 9001),
]

def start():
    print("[WealthSense] 启动所有 SSH 隧道...\n")
    processes = []
    for name, local, remote in TUNNELS:
        cmd = ["ssh", "-N", "-o", "ServerAliveInterval=60", "-o", "ExitOnForwardFailure=yes",
               "-L", f"{local}:127.0.0.1:{remote}", SSH_HOST]
        p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        processes.append((name, local, p))
        print(f"  ✓ {name:<14} localhost:{local} → 服务器:{remote}")

    pid_file = Path(__file__).parent / ".tunnel_pids.txt"
    pid_file.write_text("\n".join(str(p.pid) for _, _, p in processes))

    print(f"\n  全部 {len(processes)} 条隧道已启动，PID 已写入 {pid_file}")
    print("  按 Ctrl+C 关闭所有隧道...\n")

    def shutdown(sig=None, frame=None):
        print("\n[WealthSense] 关闭隧道...")
        for name, _, p in processes:
            p.terminate(); p.wait()
        pid_file.unlink(missing_ok=True)
        print("  已全部关闭。")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    while True: time.sleep(1)

def stop():
    pid_file = Path(__file__).parent / ".tunnel_pids.txt"
    if not pid_file.exists():
        print("[WealthSense] 未找到运行中的隧道。")
        return
    for line in pid_file.read_text().strip().split("\n"):
        try:
            os.kill(int(line), signal.SIGTERM)
        except ProcessLookupError:
            pass
    pid_file.unlink()
    print("[WealthSense] 所有隧道已关闭。")

def status():
    pid_file = Path(__file__).parent / ".tunnel_pids.txt"
    if not pid_file.exists():
        print("[WealthSense] 隧道未运行。")
        return
    running = 0
    for line in pid_file.read_text().strip().split("\n"):
        try:
            os.kill(int(line), 0); running += 1
        except (OSError, ProcessLookupError):
            pass
    print(f"[WealthSense] {running}/{len(TUNNELS)} 条隧道运行中。")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python tunnel.py [start|stop|status]")
        sys.exit(1)
    {"start": start, "stop": stop, "status": status}[sys.argv[1]]()
