#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一来源编号：把 LightVela 产出的 SDxx 全部改成 SE 段，并按 URL 全局去重。

用法（在仓库根目录、review 分支上执行）：
    python3 scripts/renumber_sources.py

规则：
  - 只处理 topics/*.md 中「## 来源与证据」里的来源行；
  - 同一 URL 全局只分配一个新编号（SE01、SE02……SE99，接 SF01……）；
  - 每个文件内 old_id -> new_id 一一对应，YAML sources 与正文 [SDxx] 同步改；
  - 同步补 sources/sources.json；
  - 生成 reports/renumber-<时间>.md。
"""
import glob
import json
import os
import re
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOPICS = os.path.join(ROOT, "topics")
SOURCES = os.path.join(ROOT, "sources", "sources.json")
REPORTS = os.path.join(ROOT, "reports")

WHITELIST = (
    "dahe.cn", "hnrb.com.cn", "hntv.tv", "hnntv.cn",
    "xinhuanet.com", "news.cn", "people.com.cn", "cnr.cn", "gmw.cn",
)
PREFIXES = [chr(c) for c in range(ord("E"), ord("Z") + 1)]

SOURCE_LINE = re.compile(r"^\s*[-*]\s*\[([A-Z]{1,2}\d{2})\]\s*(.+)$")
YAML_SOURCES = re.compile(r"^sources:\s*\[(.*?)\]\s*$", re.M)
BODY_REF = re.compile(r"\[([^\[\]]*[/·])?([A-Z]{1,2}\d{2})\]")


def make_id(n):
    idx, num = divmod(n - 1, 99)
    if idx >= len(PREFIXES):
        raise SystemExit("来源编号超过 SZ99，请拆分批次")
    return "S%s%02d" % (PREFIXES[idx], num + 1)


def is_official(url):
    host = url.split("//")[-1].split("/")[0].lower()
    return host == "gov.cn" or host.endswith(".gov.cn") or any(
        host.endswith(d) for d in WHITELIST)


def get_url(text):
    m = re.search(r"https?://\S+", text)
    return m.group(0).rstrip("，。,.;；") if m else None


def source_block(raw):
    m = re.search(r"##\s*来源与证据\s*\n(.*?)(?=\n##\s|\Z)", raw, re.S)
    return m.group(1) if m else ""


def source_lines(raw):
    out = []
    for line in source_block(raw).splitlines():
        m = SOURCE_LINE.match(line.strip())
        if m:
            out.append((m.group(1), m.group(2).strip()))
    return out


def load_sources():
    if os.path.exists(SOURCES):
        return json.load(open(SOURCES, encoding="utf-8"))
    return []


def save_sources(srcs):
    os.makedirs(os.path.dirname(SOURCES), exist_ok=True)
    json.dump(srcs, open(SOURCES, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)


def build_record(sid, text):
    url = get_url(text)
    title = re.sub(r"https?://\S+", "", text).strip(" ，。,.;；")
    publisher = title.split("《")[0].strip(" ，。,.;；") or "未注明"
    year_m = re.search(r"(20\d{2})", text)
    return {
        "id": sid,
        "title": title,
        "type": "official" if is_official(url) else "media",
        "url": url,
        "publisher": publisher,
        "year": int(year_m.group(1)) if year_m else 0,
        "checked_date": datetime.now().strftime("%Y-%m-%d"),
        "note": "LightVela 生产，统一重编号，DSH 待复核",
    }


def main():
    files = sorted(glob.glob(os.path.join(TOPICS, "*.md")))
    srcs = load_sources()
    used = {s["id"] for s in srcs}
    url_to_new = {}
    url_meta = {}
    next_n = 1
    report = ["# 来源统一重编号报告", ""]
    changed = 0
    errors = []

    def alloc(url, text):
        nonlocal next_n
        if url in url_to_new:
            return url_to_new[url]
        while True:
            sid = make_id(next_n)
            next_n += 1
            if sid not in used:
                break
        url_to_new[url] = sid
        url_meta[url] = text
        used.add(sid)
        return sid

    for path in files:
        raw = open(path, encoding="utf-8").read()
        pairs = source_lines(raw)
        if not pairs:
            continue
        file_map = {}
        conflict = False
        for old, text in pairs:
            url = get_url(text)
            if not url:
                errors.append(f"{os.path.basename(path)}: {old} 缺少 URL")
                conflict = True
                continue
            new = alloc(url, text)
            if old in file_map and file_map[old] != new:
                errors.append(
                    f"{os.path.basename(path)}: {old} 同时指向不同 URL")
                conflict = True
            file_map[old] = new
        if conflict:
            continue

        def yaml_repl(m):
            items = [x.strip() for x in m.group(1).split(",") if x.strip()]
            return "sources: [" + ", ".join(file_map.get(x, x) for x in items) + "]"

        new_raw = YAML_SOURCES.sub(yaml_repl, raw)

        def ref_repl(m):
            prefix = m.group(1) or ""
            return "[" + prefix + file_map.get(m.group(2), m.group(2)) + "]"

        new_raw = BODY_REF.sub(ref_repl, new_raw)

        if new_raw != raw:
            open(path, "w", encoding="utf-8").write(new_raw)
            changed += 1
            report.append(f"## {os.path.basename(path)}")
            for old, new in sorted(file_map.items()):
                report.append(f"- {old} -> {new}")
            report.append("")

    added = 0
    for url, sid in sorted(url_to_new.items(), key=lambda x: x[1]):
        if sid in {s["id"] for s in srcs}:
            continue
        srcs.append(build_record(sid, url_meta[url]))
        added += 1
    save_sources(srcs)

    os.makedirs(REPORTS, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    rp = os.path.join(REPORTS, f"renumber-{stamp}.md")
    report.insert(2, f"- 修改文件：{changed}")
    report.insert(3, f"- 新增来源：{added}")
    report.insert(4, f"- 新编号：{len(url_to_new)} 个")
    if errors:
        report += ["", "## 错误"] + [f"- {e}" for e in errors]
    open(rp, "w", encoding="utf-8").write("\n".join(report))
    print(f"修改 {changed} 篇，新增来源 {added} 条，报告 {rp}")
    if errors:
        for e in errors:
            print("[ERROR]", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
