#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
砺行知识库 · LightVela 产出自动入库脚本 v1.0

用法（在仓库根目录执行）：
    python scripts/ingest.py

流程：
  1. 扫描 inbox/ 下的 .zip 与 .md；
  2. zip 解压到 processing/<zip名>/；
  3. 逐篇解析 YAML、补 sources.json、校验格式/来源/字数/查重；
  4. 通过 -> topics/；不通过 -> rework/（附 .reason.txt）；
  5. 生成 reports/ingest-<时间>.md。

依赖：仅 Python 3.8+ 标准库。
"""
import glob
import json
import os
import re
import shutil
import sys
import zipfile
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOPICS = os.path.join(ROOT, "topics")
SOURCES = os.path.join(ROOT, "sources", "sources.json")
INBOX = os.path.join(ROOT, "inbox")
PROCESSING = os.path.join(ROOT, "processing")
REWORK = os.path.join(ROOT, "rework")
REPORTS = os.path.join(ROOT, "reports")

REQUIRED = ["id", "title", "category", "tags", "related", "evidence_level",
            "sources", "created", "updated", "status"]
VALID_EVIDENCE = ("官方", "研究", "综合", "存疑")
VALID_STATUS = ("draft", "reviewed")
VALID_CATEGORY = ("A", "B", "C", "D")

WHITELIST = (
    "dahe.cn", "hnrb.com.cn", "hntv.tv", "hnntv.cn",
    "xinhuanet.com", "news.cn", "people.com.cn", "cnr.cn", "gmw.cn",
)
RESERVED_SOURCE_PREFIX = ("SA", "SB", "SC", "SD")

PLACEHOLDERS = ("待补", "TODO", "todo", "占位", "编造", "示例链接", "xxx")


def log(msg):
    print(msg)


def parse_yaml(text):
    """够用即可：键: 值 / [a, b] 列表。"""
    meta = {}
    for line in text.splitlines():
        if not line.strip() or ":" not in line:
            continue
        k, _, v = line.partition(":")
        v = v.strip()
        if v.startswith("[") and v.endswith("]"):
            inner = v[1:-1].strip()
            meta[k.strip()] = [x.strip() for x in inner.split(",")] if inner else []
        else:
            meta[k.strip()] = v
    return meta


def parse_topic(path):
    raw = open(path, encoding="utf-8").read()
    m = re.match(r"^---\n(.*?)\n---\n", raw, re.S)
    if not m:
        raise ValueError("缺少 YAML 元数据头")
    return parse_yaml(m.group(1)), raw[m.end():]


def load_sources():
    if os.path.exists(SOURCES):
        return json.load(open(SOURCES, encoding="utf-8"))
    return []


def save_sources(srcs):
    os.makedirs(os.path.dirname(SOURCES), exist_ok=True)
    json.dump(srcs, open(SOURCES, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)


def is_official(url):
    host = url.split("//")[-1].split("/")[0].lower()
    return host == "gov.cn" or host.endswith(".gov.cn") or any(
        host.endswith(d) for d in WHITELIST)


def guess_type(url):
    return "official" if is_official(url) else "media"


def extract_source_lines(body):
    """返回 [(id, line)]，来源行格式：- [SD01] 机构《标题》，日期，URL"""
    block = re.search(r"##\s*来源与证据\s*\n(.*?)(?=\n##\s|\Z)", body, re.S)
    text = block.group(1) if block else body
    out = []
    for line in text.splitlines():
        m = re.match(r"\s*[-*]\s*\[([A-Z]{1,2}\d{2})\]\s*(.+)$", line.strip())
        if m:
            out.append((m.group(1), m.group(2).strip()))
    return out


def add_sources(srcs, pairs, errors):
    by_id = {s["id"]: s for s in srcs}
    for sid, text in pairs:
        url_m = re.search(r"(https?://\S+)", text)
        if not url_m:
            errors.append(f"来源 {sid} 缺少 URL：{text[:60]}")
            continue
        url = url_m.group(1).rstrip("，。,.;；")
        if sid in by_id:
            old = by_id[sid].get("url", "")
            if old and old != url:
                errors.append(
                    f"来源 ID 冲突：{sid} 已存在且 URL 不同（旧 {old} / 新 {url}）")
            continue
        year_m = re.search(r"(20\d{2})", text)
        title = re.sub(r"(https?://\S+)", "", text).strip(" ，。,.;；")
        publisher = title.split("《")[0].strip(" ，。,.;；") or "未注明"
        srcs.append({
            "id": sid,
            "title": title,
            "type": guess_type(url),
            "url": url,
            "publisher": publisher,
            "year": int(year_m.group(1)) if year_m else 0,
            "checked_date": datetime.now().strftime("%Y-%m-%d"),
            "note": "LightVela 生产，DSH 待复核",
        })
        by_id[sid] = srcs[-1]


def cn_len(text):
    return len(re.sub(r"[^\u4e00-\u9fff]", "", text))


def validate(meta, body, path, existing_ids):
    errs = []
    tid = str(meta.get("id", ""))
    if not re.match(r"^[A-Z]\d{2}$", tid):
        errs.append(f"id 非法：{tid}")
    elif tid != os.path.basename(path)[:3]:
        errs.append(f"id 与文件名不一致：{tid} vs {os.path.basename(path)}")
    elif tid in existing_ids:
        errs.append(f"id 重复：{tid}")
    for f in REQUIRED:
        if f not in meta or meta[f] in (None, ""):
            errs.append(f"缺少字段：{f}")
    if meta.get("category") not in VALID_CATEGORY:
        errs.append(f"category 非法：{meta.get('category')}")
    ev = meta.get("evidence_level")
    if isinstance(ev, list) or ev not in VALID_EVIDENCE:
        errs.append(f"evidence_level 非法：{ev}")
    if meta.get("status") not in VALID_STATUS:
        errs.append(f"status 非法：{meta.get('status')}")
    for f in ("tags", "related", "sources"):
        if f in meta and not isinstance(meta[f], list):
            errs.append(f"{f} 必须是列表")

    for sec in ("## ⚡ 快速知识卡", "## 📖 深度专题", "## 来源与证据", "## 关联专题"):
        if sec not in body:
            errs.append(f"缺少章节：{sec}")

    length = cn_len(body)
    min_len = 2000 if tid.startswith("W") else 1200
    if tid.startswith("Q"):
        min_len = 800
    if length < min_len:
        errs.append(f"正文过短：{length} 字（要求 ≥{min_len}）")

    pairs = extract_source_lines(body)
    if len(pairs) < 5:
        errs.append(f"来源不足：{len(pairs)} 条（至少 5 条）")
    for sid in meta.get("sources", []):
        if str(sid)[:2] in RESERVED_SOURCE_PREFIX:
            errs.append(
                f"来源编号 {sid} 属于现有 SA/SB/SC/SD 段，LightVela 请从 SE01 起")
    urls = re.findall(r"https?://\S+", body)
    if len(urls) < 5:
        errs.append(f"URL 不足：{len(urls)} 条（至少 5 条）")
    official = sum(1 for u in urls if is_official(u))
    if official < 2:
        errs.append(f"官方来源不足：{official} 条（至少 2 条，含 *.gov.cn）")

    for p in PLACEHOLDERS:
        if p in body or p in str(meta):
            errs.append(f"含占位/可疑字样：{p}")

    # 来源 ID 必须与 YAML sources 一致
    src_ids = set(meta.get("sources", []))
    line_ids = {sid for sid, _ in pairs}
    if src_ids - line_ids:
        errs.append(f"YAML sources 未在正文列出：{sorted(src_ids - line_ids)}")
    return errs, pairs


def ingest_file(path, srcs, existing_ids, report):
    name = os.path.basename(path)
    try:
        meta, body = parse_topic(path)
    except Exception as e:
        report["fail"].append((name, [f"解析失败：{e}"]))
        return
    errors, pairs = validate(meta, body, path, existing_ids)
    if errors:
        report["fail"].append((name, errors))
        return
    add_sources(srcs, pairs, errors)
    if errors:
        report["fail"].append((name, errors))
        return
    dest = os.path.join(TOPICS, name)
    if os.path.exists(dest):
        report["fail"].append((name, ["目标文件已存在，拒绝覆盖"]))
        return
    shutil.copy2(path, dest)
    existing_ids.add(str(meta["id"]))
    report["ok"].append(name)


def main():
    for d in (INBOX, PROCESSING, REWORK, REPORTS, TOPICS):
        os.makedirs(d, exist_ok=True)
    srcs = load_sources()
    existing_ids = set()
    for f in glob.glob(os.path.join(TOPICS, "*.md")):
        try:
            m, _ = parse_topic(f)
            existing_ids.add(str(m.get("id")))
        except Exception:
            pass

    report = {"ok": [], "fail": []}
    md_files = []

    for z in glob.glob(os.path.join(INBOX, "*.zip")):
        base = os.path.splitext(os.path.basename(z))[0]
        out = os.path.join(PROCESSING, base)
        if os.path.exists(out):
            shutil.rmtree(out)
        os.makedirs(out, exist_ok=True)
        try:
            with zipfile.ZipFile(z) as zf:
                zf.extractall(out)
            md_files += glob.glob(os.path.join(out, "**", "*.md"), recursive=True)
            log(f"[ZIP] {os.path.basename(z)} -> {out}")
        except Exception as e:
            report["fail"].append((os.path.basename(z), [f"解压失败：{e}"]))

    md_files += glob.glob(os.path.join(INBOX, "*.md"))

    for p in md_files:
        ingest_file(p, srcs, existing_ids, report)

    save_sources(srcs)

    for name, errs in report["fail"]:
        base = os.path.splitext(name)[0]
        with open(os.path.join(REWORK, base + ".reason.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(errs))

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    rp = os.path.join(REPORTS, f"ingest-{stamp}.md")
    with open(rp, "w", encoding="utf-8") as f:
        f.write(f"# 入库报告 {stamp}\n\n")
        f.write(f"- 通过：{len(report['ok'])}\n- 失败：{len(report['fail'])}\n")
        f.write(f"- 来源总数：{len(srcs)}\n\n## 通过\n")
        for n in report["ok"]:
            f.write(f"- {n}\n")
        f.write("\n## 失败\n")
        for n, errs in report["fail"]:
            f.write(f"### {n}\n")
            for e in errs:
                f.write(f"- {e}\n")
    log(f"通过 {len(report['ok'])}，失败 {len(report['fail'])}，报告：{rp}")
    return 0 if not report["fail"] else 1


if __name__ == "__main__":
    sys.exit(main())