#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 W03-W07（SE39-SE88）与 D11（SF01-SF08）的来源行合并进 sources/sources.json。

来源行的原始文本在 topics/*.md 的「## 来源与证据」小节里，格式：
    - [SE39] 河南省政府门户网《标题》，2026-07-17，https://...
本脚本解析该格式，拆出 title / publisher / year / url / note，
按既有 SE01..SE38 的条目结构追加。已存在的 ID 默认跳过（幂等）。

用法：
    python3 scripts/add_batch1_sources.py            # 写入
    python3 scripts/add_batch1_sources.py --dry-run  # 只报告
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "sources" / "sources.json"
CHECKED = "2026-10-20"

# 官方白名单判定（PRODUCTION_PACK.md §2）
OFFICIAL_SUFFIX = ".gov.cn"
OFFICIAL_DOMAINS = {
    "dahe.cn", "hnrb.com.cn", "hntv.tv", "hnntv.cn", "andaily.cn", "henandaily.cn",
    "xinhuanet.com", "news.cn", "people.com.cn", "gmw.cn", "cnr.cn",
}
MEDIA_DOMAINS = {
    "chinanews.com.cn", "chinanews.com", "stcn.com", "cri.cn", "ce.cn",
    "yicai.com", "21jingji.com", "caixin.com", "thepaper.cn", "jiemian.com",
}
FILES = [
    "topics/W03-周报-2026-07-19.md",
    "topics/W04-周报-2026-07-26.md",
    "topics/W05-周报-2026-08-02.md",
    "topics/W06-周报-2026-08-09.md",
    "topics/W07-周报-2026-08-16.md",
    "topics/D11-河南高标准农田.md",
    "topics/D12-河南粮食安全.md",
    "topics/D13-河南民营经济.md",
    "topics/D14-河南统一大市场.md",
    "topics/D15-河南新质生产力.md",
    "topics/W08-周报-2026-08-23.md",
    "topics/W09-周报-2026-08-30.md",
    "topics/W10-周报-2026-09-06.md",
    "topics/W11-周报-2026-09-13.md",
    "topics/D16-河南文旅文创融合.md",
    "topics/W12-周报-2026-09-20.md",
    "topics/D17-河南县域经济高质量发展.md",
]
LINE_RE = re.compile(r"^-\s*\[(S[EF]\d{2,3})\]\s*(.+)$")
URL_RE = re.compile(r"https?://[^\s，,）)]+")
DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
BOOK_RE = re.compile(r"《([^》]+)》")


def classify(url, publisher):
    """按域名判断 official / media，白名单外的不猜 official。"""
    host = re.sub(r"^https?://", "", url).split("/")[0].lower()
    bare = host[4:] if host.startswith("www.") else host
    if bare.endswith(OFFICIAL_SUFFIX):
        return "official"
    for d in OFFICIAL_DOMAINS:
        if bare == d or bare.endswith("." + d):
            return "official"
    for d in MEDIA_DOMAINS:
        if bare == d or bare.endswith("." + d):
            return "media"
    return "media"


def parse_line(sid, rest, path):
    """把 '- [SE39] 机构《标题》，日期，URL （备注）' 拆成字段。"""
    m_url = URL_RE.search(rest)
    if not m_url:
        raise ValueError(f"{sid}: 找不到 URL -> {rest[:80]}")
    url = m_url.group(0)
    before = rest[: m_url.start()].rstrip("，, ").strip()
    after = rest[m_url.end():].strip()

    m_book = BOOK_RE.search(before)
    if m_book:
        title_text = m_book.group(1)
        publisher = before[: m_book.start()].strip()
    else:
        title_text = before
        publisher = before

    m_date = DATE_RE.search(before)
    year = int(m_date.group(1)) if m_date else None
    date = m_date.group(0) if m_date else ""

    title = f"{publisher}《{title_text}》" if m_book else title_text
    if date:
        title = f"{title}，{date}"
    note = f"来自 {path}，LightVela 生产，DSH 待复核"
    if after:
        note = f"{note}；原文备注：{after.lstrip('（）() ').rstrip('）) ')}"
    return {
        "id": sid,
        "title": title,
        "type": classify(url, publisher),
        "url": url,
        "publisher": publisher or "未知",
        "year": year,
        "checked_date": CHECKED,
        "note": note,
    }


def collect():
    parsed, order = {}, []
    for rel in FILES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        m = re.search(r"##\s*来源与证据(.*?)(?=\n##\s|\Z)", text, re.S)
        if not m:
            raise SystemExit(f"{rel}: 没有「## 来源与证据」小节")
        for line in m.group(1).splitlines():
            mm = LINE_RE.match(line.strip())
            if not mm:
                continue
            sid, rest = mm.group(1), mm.group(2).strip()
            if sid in parsed:
                if parsed[sid]["url"] != URL_RE.search(rest).group(0):
                    raise SystemExit(
                        f"ID 冲突：{sid} 在 {rel} 与 {parsed[sid]['src']} 指向不同 URL")
                continue
            entry = parse_line(sid, rest, rel)
            entry["src"] = rel
            parsed[sid] = entry
            order.append(sid)
    return parsed, order


def main():
    dry = "--dry-run" in sys.argv
    data = json.loads(SRC.read_text(encoding="utf-8"))
    have = {x["id"] for x in data}
    parsed, order = collect()

    def sort_key(sid):
        return (sid[:2], int(sid[2:]))

    fresh = []
    for sid in sorted(order, key=sort_key):
        if sid in have:
            print(f"跳过（已存在）: {sid}")
            continue
        entry = dict(parsed[sid])
        entry.pop("src", None)
        fresh.append(entry)

    print(f"解析 {len(parsed)} 条；新增 {len(fresh)} 条")
    if not fresh:
        print("无新增，sources.json 保持", len(data), "条")
        return
    for e in fresh:
        print(f"  + {e['id']:5s} {e['type']:8s} {e['publisher'][:34]}")
    if dry:
        print("[dry-run] 未写入")
        return

    data.extend(fresh)
    SRC.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"写入完成：{len(data)} 条")


if __name__ == "__main__":
    main()
