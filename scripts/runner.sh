#!/usr/bin/env bash
set -u

cd "$(dirname "$0")/.."
export GIT_TERMINAL_PROMPT=0

while true; do
    python3 scripts/runner_once.py || true

    ahead="$(git rev-list --count '@{u}..HEAD' 2>/dev/null || echo 0)"
    if [ "${ahead:-0}" -gt 0 ]; then
        echo "[runner] local ahead by ${ahead}; retrying push"
        timeout 20 git push origin main || echo "[runner] push failed; retry next loop"
    fi

    sleep 30
done