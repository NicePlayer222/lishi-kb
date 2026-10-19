#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LightVela runner：从 GitHub 仓库取一条命令，调用 hermes -z 执行，把结果写回 outbox。

由 scripts/runner.sh 循环调用；也可以手动执行一次：
    python3 scripts/runner_once.py

命令文件：inbox/command.json
  {
    "id": "20261019-001",
    "status": "pending",
    "prompt": "要发给 Hermes 的完整任务",
    "timeout": 3600
  }

结果文件：outbox/<id>.json
  {id, status, exit_code, stdout, stderr, duration_sec, started_at, finished_at}
"""
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "inbox" / "command.json"
DONE_DIR = ROOT / "inbox" / "done"
OUTBOX = ROOT / "outbox"
LOCK = Path.home() / ".lishi-runner.once.lock"
HERMES = os.environ.get("HERMES_BIN") or shutil.which("hermes") or "hermes"


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def git(*args):
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=120)


def pull():
    r = git("pull", "--rebase", "--autostash", "-q")
    if r.returncode != 0:
        print("[runner] pull failed:", r.stderr.strip()[:300])


def commit_push(message):
    git("add", "-A")
    diff = git("diff", "--cached", "--quiet")
    if diff.returncode != 0:
        git("commit", "-m", message)
    for _ in range(3):
        r = git("push", "-q")
        if r.returncode == 0:
            return True
        pull()
        time.sleep(5)
    print("[runner] push failed after retries")
    return False


def main():
    pull()
    if not INBOX.exists():
        return 0

    try:
        cmd = json.loads(INBOX.read_text(encoding="utf-8"))
    except Exception as e:
        print("[runner] bad command json:", e)
        return 1
    if cmd.get("status") != "pending":
        return 0
    if LOCK.exists():
        print("[runner] another run holds the lock; skip")
        return 0

    LOCK.write_text(str(os.getpid()), encoding="utf-8")
    started = now()
    t0 = time.time()
    cmd["status"] = "running"
    cmd["started_at"] = started
    INBOX.write_text(json.dumps(cmd, ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8")
    commit_push(f"runner: start {cmd.get('id', 'unknown')}")

    stdout, stderr, code = "", "", -1
    try:
        p = subprocess.run(
            [HERMES, "--yolo", "-z", cmd["prompt"]],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=int(cmd.get("timeout", 3600)),
        )
        stdout, stderr, code = p.stdout, p.stderr, p.returncode
    except FileNotFoundError:
        stderr = f"hermes not found: {HERMES}"
    except subprocess.TimeoutExpired as e:
        stdout = (e.stdout or "") if isinstance(e.stdout, str) else ""
        stderr = f"timeout after {cmd.get('timeout', 3600)}s"
        code = 124
    except Exception as e:
        stderr = f"{type(e).__name__}: {e}"
    finally:
        LOCK.unlink(missing_ok=True)

    finished = now()
    result = {
        "id": cmd.get("id", "unknown"),
        "status": "done" if code == 0 else "failed",
        "exit_code": code,
        "stdout": stdout,
        "stderr": stderr,
        "duration_sec": round(time.time() - t0, 1),
        "started_at": started,
        "finished_at": finished,
    }
    OUTBOX.mkdir(exist_ok=True)
    DONE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTBOX / f"{result['id']}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")

    cmd["status"] = "done"
    cmd["finished_at"] = finished
    cmd["result_file"] = str(out_path.relative_to(ROOT))
    (DONE_DIR / f"{result['id']}.json").write_text(
        json.dumps(cmd, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    INBOX.unlink(missing_ok=True)

    commit_push(f"runner: {result['status']} {result['id']}")
    print(f"[runner] {result['status']} {result['id']} exit={code} "
          f"{result['duration_sec']}s")
    return 0 if code == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
