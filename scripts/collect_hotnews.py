#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""河南时政采集器：抓权威源当天/本周条目，输出候选清单供后续加工。

设计原则：
- 只读，不改 topics/；输出落到 data/hotnews/<日期>.json 与 .md
- 增量：已抓过的 URL 记在 data/hotnews/seen.json，避免重复
- 白名单域名硬编码，非白名单一律丢弃
- 失败不抛异常，记入 errors，让定时任务照常退出 0

用法：
    python3 scripts/collect_hotnews.py              # 采集近 7 天
    python3 scripts/collect_hotnews.py --days 2     # 只采近 2 天
    python3 scripts/collect_hotnews.py --dry-run    # 只打印不写文件
"""
import argparse
import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "hotnews"
SEEN = OUT_DIR / "seen.json"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"

# 白名单源：name -> 列表页 URL 与链接提取规则
SOURCES = [
    {
        "name": "河南省人民政府",
        "index": "https://www.henan.gov.cn/",
        "pattern": r'https://www\.henan\.gov\.cn/(\d{4})/(\d{2})-(\d{2})/(\d+)\.html',
        "require_henan": False,
    },
    {
        "name": "大河网新闻",
        "index": "https://news.dahe.cn/",
        "pattern": r'https://news\.dahe\.cn/(\d{4})/(\d{2})-(\d{2})/(\d+)\.html',
        "require_henan": True,
    },
]
OFFICIAL_SUFFIX = ".gov.cn"
OFFICIAL_DOMAINS = {
    "dahe.cn", "hnrb.com.cn", "hntv.tv", "hnntv.cn", "henandaily.cn",
    "xinhuanet.com", "news.cn", "people.com.cn", "gmw.cn", "cnr.cn",
}

# 相关性过滤：标题命中任一关键词才保留（考公时政/政策/民生口径）
RELEVANT = [
    "省委", "省政府", "市委", "市政府", "县委", "县政府", "书记", "省长", "市长",
    "全会", "常委会", "常务会议", "党组", "部署", "印发", "出台", "通知", "意见",
    "方案", "规划", "条例", "办法", "政策", "改革", "试点", "示范",
    "乡村", "振兴", "粮食", "农业", "农田", "脱贫", "返贫", "帮扶",
    "就业", "社保", "医保", "养老", "教育", "医疗", "住房", "物价",
    "营商", "民营", "企业", "产业", "项目", "投资", "消费", "外贸",
    "科技", "创新", "人才", "数字", "智能", "新质",
    "生态", "环保", "污染", "碳", "能源", "水利", "防汛", "抗旱",
    "治理", "基层", "社区", "网格", "矛盾", "信访", "安全", "应急",
    "交通", "物流", "枢纽", "开放", "招商", "统一大市场",
    "文化", "文旅", "文物", "非遗",
    "党建", "干部", "作风", "减负", "形式主义", "廉政",
    "数据", "统计", "GDP", "增长", "运行", "发布会",
]
# 明显无关的栏目词，命中即丢弃（即使同时命中 RELEVANT）
EXCLUDE = [
    "体育", "足球", "篮球", "球员", "赛事", "夺冠", "奥运",
    "娱乐", "明星", "综艺", "影视", "演唱会", "绯闻",
    "星座", "游戏", "电竞", "彩票",
]
# 省级源用 RELEVANT 即可；媒体站（大河网）首页混入全国/外地新闻，
# 必须再命中河南相关词，才认为与河南有关。
HENAN_MARKERS = [
    "河南", "豫", "郑州", "开封", "洛阳", "平顶山", "安阳", "鹤壁", "新乡",
    "焦作", "濮阳", "许昌", "漯河", "三门峡", "南阳", "商丘", "信阳", "周口",
    "驻马店", "济源", "航空港", "中原", "黄河", "兰考", "林州", "固始",
]


def relevant(title, require_henan=False):
    if any(x in title for x in EXCLUDE):
        return False
    if not any(k in title for k in RELEVANT):
        return False
    if require_henan and not any(h in title for h in HENAN_MARKERS):
        return False
    return True


def ctx():
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx()) as r:
        raw = r.read()
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def host_of(url):
    return re.sub(r"^https?://", "", url).split("/")[0].lower()


def is_official(url):
    bare = host_of(url)
    if bare.startswith("www."):
        bare = bare[4:]
    if bare.endswith(OFFICIAL_SUFFIX):
        return True
    return any(bare == d or bare.endswith("." + d) for d in OFFICIAL_DOMAINS)


def extract(html, src, since):
    """从列表页提取 (url, title, date)。标题取 <a> 的文本。"""
    out = []
    pat = re.compile(src["pattern"])
    # 逐个 <a ...>...</a> 扫描，避免跨标签抓错
    for m in re.finditer(r'<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.S | re.I):
        href, inner = m.group(1), m.group(2)
        pm = pat.search(href)
        if not pm:
            continue
        y, mo, d = int(pm.group(1)), int(pm.group(2)), int(pm.group(3))
        try:
            day = date(y, mo, d)
        except ValueError:
            continue
        if day < since:
            continue
        title = re.sub(r"<[^>]+>", "", inner)
        title = re.sub(r"\s+", " ", title).strip()
        if len(title) < 6:
            continue
        if not relevant(title, require_henan=src.get("require_henan", False)):
            continue
        out.append({"url": href, "title": title, "date": day.isoformat(),
                    "source": src["name"], "official": is_official(href)})
    return out


def dedupe(items):
    seen, out = set(), []
    for it in items:
        key = it["url"]
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    since = date.today() - timedelta(days=args.days)
    known = set()
    if SEEN.exists():
        try:
            known = set(json.loads(SEEN.read_text(encoding="utf-8")))
        except Exception:
            known = set()

    all_items, errors = [], []
    for src in SOURCES:
        try:
            html = fetch(src["index"])
            items = extract(html, src, since)
            all_items.extend(items)
            print(f"[ok] {src['name']}: {len(items)} 条")
        except Exception as e:
            errors.append({"source": src["name"], "error": f"{type(e).__name__}: {e}"})
            print(f"[fail] {src['name']}: {type(e).__name__}")

    all_items = dedupe(all_items)
    fresh = [x for x in all_items if x["url"] not in known]
    fresh.sort(key=lambda x: (x["date"], x["source"]), reverse=True)

    official_n = sum(1 for x in fresh if x["official"])
    print(f"\n合计 {len(all_items)} 条（去重后），新增 {len(fresh)} 条，其中官方域名 {official_n} 条")
    if errors:
        print("失败源：" + "; ".join(f"{e['source']}({e['error'][:40]})" for e in errors))

    if args.dry_run:
        for x in fresh[:15]:
            print(f"  {x['date']} [{x['source']}] {x['title'][:50]}")
        print("[dry-run] 未写入")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    payload = {
        "collected_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "since": since.isoformat(),
        "count": len(fresh),
        "official_count": official_n,
        "errors": errors,
        "items": fresh,
    }
    (OUT_DIR / f"{today}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [f"# 河南时政候选 · {today}", "",
             f"> 采集时间 {payload['collected_at']}；近 {args.days} 天；"
             f"新增 {len(fresh)} 条，官方 {official_n} 条。", ""]
    for x in fresh:
        flag = "官方" if x["official"] else "媒体"
        lines.append(f"- {x['date']} [{flag}·{x['source']}] {x['title']}")
        lines.append(f"  {x['url']}")
    if errors:
        lines += ["", "## 采集失败", ""]
        lines += [f"- {e['source']}：{e['error']}" for e in errors]
    (OUT_DIR / f"{today}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    known |= {x["url"] for x in fresh}
    SEEN.write_text(json.dumps(sorted(known), ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")
    print(f"已写入 data/hotnews/{today}.json 与 .md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
