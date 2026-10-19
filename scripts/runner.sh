#!/usr/bin/env bash
# LightVela runner 循环：每 30 秒拉一次仓库，有命令就执行一次。
# 启动：nohup bash scripts/runner.sh > ~/lishi-runner.log 2>&1 &
set -u
cd "$(dirname "$0")/.." || exit 1

if ! command -v hermes >/dev/null 2>&1; then
  echo "[runner] hermes not found in PATH" >&2
  exit 1
fi

# 防止重复启动（有 flock 用 flock，没有就退化为 pid 文件）
if command -v flock >/dev/null 2>&1; then
  exec 9>"$HOME/.lishi-runner.loop.lock"
  if ! flock -n 9; then
    echo "[runner] already running" >&2
    exit 1
  fi
else
  PIDFILE="$HOME/.lishi-runner.loop.pid"
  if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE" 2>/dev/null)" 2>/dev/null; then
    echo "[runner] already running" >&2
    exit 1
  fi
  echo $$ > "$PIDFILE"
fi

echo "[runner] started at $(date -Is) in $(pwd)"
while true; do
  git pull --rebase --autostash -q 2>/dev/null || true
  python3 scripts/runner_once.py || true
  sleep 30
done
