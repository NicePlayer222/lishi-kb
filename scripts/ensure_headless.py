#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""确保 agent 浏览器处于无头模式（不弹窗）。

背景：dsh-ego-browser 只在进程环境里没有 EGO_LINUX_HEADLESS 时才自行判断，
DSH 重启后可能退回有头模式并弹出 Chrome 窗口。快捷方式/系统环境变量都不够
可靠（DSH 升级会重建快捷方式，部分启动路径不继承用户变量）。

本脚本由 Agent 在每次用浏览器前调用：
  - 读 %LOCALAPPDATA%\\ego-lite-linux\\browser.json 的 headless 字段
  - 正常（true 且无可见窗口）-> 直接返回，不做任何事
  - 异常（false 或存在可见窗口）-> 停止浏览器、清除状态、以无头模式重启

用法：
    python scripts/ensure_headless.py            # 检查并按需修复
    python scripts/ensure_headless.py --check    # 只检查，不修复
退出码：0 = 无头正常或已修复；1 = 需要人工介入。
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

EGO_BIN = Path(os.path.expandvars(
    r"%LOCALAPPDATA%\..\..\..\Users") )  # 占位，下面用真实路径覆盖
EGO_BIN = Path(r"C:\Users\95889\.dsh\profiles\desktop\node_modules"
               r"\dsh-ego-browser\runtime\ego-linux\bin\ego-browser.mjs")
STATE = Path(os.path.expandvars(r"%LOCALAPPDATA%\ego-lite-linux\browser.json"))
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
NODE = "node"


def visible_windows():
    """返回标题含 LightVela/ling/知识库 等 agent 常见页面标题的可见 Chrome 数量。
    更稳妥的做法：直接查 browser.json 里 pid 的 MainWindowHandle。"""
    if not STATE.exists():
        return None, None
    try:
        st = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return None, None
    pid = st.get("pid")
    if not pid:
        return None, st
    ps = (f"$p = Get-Process -Id {pid} -ErrorAction SilentlyContinue; "
          f"if ($p) {{ $p.MainWindowHandle }} else {{ -1 }}")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, timeout=25)
        out = (r.stdout or "").strip().splitlines()
        handle = int(out[-1]) if out and out[-1].lstrip("-").isdigit() else -1
    except Exception:
        handle = -2
    return handle, st


def stop_browser():
    env = dict(os.environ, EGO_LINUX_CHROME=CHROME)
    try:
        subprocess.run([NODE, str(EGO_BIN), "--stop"], env=env,
                       capture_output=True, text=True, timeout=40)
    except Exception:
        pass


def start_headless():
    env = dict(os.environ, EGO_LINUX_HEADLESS="1", EGO_LINUX_CHROME=CHROME)
    script = 'console.log(JSON.stringify({ok:true}))'
    try:
        r = subprocess.run([NODE, str(EGO_BIN), "nodejs"], input=script,
                           env=env, capture_output=True, text=True, timeout=90)
        return r.returncode == 0, (r.stdout or "")[:120] + (r.stderr or "")[:200]
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只检查不修复")
    args = ap.parse_args()

    handle, st = visible_windows()
    if st is None:
        print("状态：浏览器未运行（下次启动会自动判断）")
        return 0
    headless = st.get("headless")
    print(f"状态：headless={headless} pid={st.get('pid')} 窗口句柄={handle}")

    ok = headless is True and handle == 0
    if ok:
        print("结论：无头正常，无需处理")
        return 0
    if args.check:
        print("结论：异常（有头运行或窗口可见），需要修复")
        return 1

    print("结论：异常，开始修复…")
    stop_browser()
    try:
        STATE.unlink(missing_ok=True)
    except Exception:
        pass
    if not EGO_BIN.exists():
        print(f"[FAIL] 找不到 ego-browser：{EGO_BIN}")
        return 1
    good, log = start_headless()
    handle2, st2 = visible_windows()
    if good and st2 and st2.get("headless") is True and handle2 == 0:
        print(f"结论：已修复，headless=True pid={st2.get('pid')} 无可见窗口")
        return 0
    print(f"[FAIL] 修复后仍不正常：headless={st2.get('headless') if st2 else None} "
          f"句柄={handle2}\n      启动输出：{log[:300]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
