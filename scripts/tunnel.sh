#!/bin/bash
# WealthSense SSH 隧道一键启动脚本
# 在 Git Bash 中运行: bash scripts/tunnel.sh [start|stop|status]
# 隧道运行中按 Ctrl+C 关闭

SSH_HOST="ubuntu@114.132.213.216"

declare -A TUNNELS=(
  ["MySQL"]="13306:3306"
  ["Redis"]="6379:6379"
  ["Neo4j-HTTP"]="7474:7474"
  ["Neo4j-Bolt"]="7687:7687"
  ["Milvus"]="19530:19530"
  ["Milvus-Mgmt"]="9091:9091"
  ["MinIO-API"]="9000:9000"
  ["MinIO-Console"]="9001:9001"
)

PID_FILE="$(dirname "$0")/.tunnel_pids.txt"

cmd_start() {
  echo "[WealthSense] 启动 8 条 SSH 隧道..."
  rm -f "$PID_FILE"

  for name in "${!TUNNELS[@]}"; do
    local_port="${TUNNELS[$name]%%:*}"
    remote_port="${TUNNELS[$name]##*:}"
    ssh -N \
      -o ServerAliveInterval=60 \
      -o ExitOnForwardFailure=yes \
      -L "127.0.0.1:${local_port}:127.0.0.1:${remote_port}" \
      "$SSH_HOST" &
    pid=$!
    echo "$pid" >> "$PID_FILE"
    echo "  ✓ ${name} (localhost:${local_port})"
  done

  echo ""
  echo "  全部隧道已启动，PID 已写入 $PID_FILE"
  echo "  按 Ctrl+C 关闭..."
  wait
}

cmd_stop() {
  if [ ! -f "$PID_FILE" ]; then
    echo "[WealthSense] 未找到运行中的隧道。"
    return
  fi
  while read -r pid; do
    kill "$pid" 2>/dev/null
  done < "$PID_FILE"
  rm -f "$PID_FILE"
  echo "[WealthSense] 隧道已全部关闭。"
}

cmd_status() {
  if [ ! -f "$PID_FILE" ]; then
    echo "[WealthSense] 隧道未运行。"
    return
  fi
  total=0 running=0
  while read -r pid; do
    total=$((total + 1))
    if kill -0 "$pid" 2>/dev/null; then running=$((running + 1)); fi
  done < "$PID_FILE"
  echo "[WealthSense] ${running}/${total} 条隧道运行中。"
}

trap 'cmd_stop; exit 0' INT TERM

case "${1:-start}" in
  start)  cmd_start ;;
  stop)   cmd_stop ;;
  status) cmd_status ;;
  *)      echo "用法: $0 [start|stop|status]" ;;
esac
