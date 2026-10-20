#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
砺行备考知识库构建脚本 v1.1
从 topics/*.md 原始数据重建 index/topics.json 与 site/index.html。

用法（在知识库根目录执行）：
    python scripts/build.py          # 构建索引与 HTML
    python scripts/build.py --check  # 仅校验，不写文件

依赖：仅 Python 3.8+ 标准库（YAML 头用内置简易解析器处理，无需 PyYAML；
      若环境装有 PyYAML 会自动优先使用）。
Windows：安装 Python 后双击运行或在命令行执行 `py scripts\build.py`。
"""
import json, os, re, sys, glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOPICS_DIR = os.path.join(ROOT, 'topics')
INDEX_PATH = os.path.join(ROOT, 'index', 'topics.json')
SOURCES_PATH = os.path.join(ROOT, 'sources', 'sources.json')
SITE_DIR = os.path.join(ROOT, 'site')
import datetime
GENERATED_DATE = datetime.date.today().isoformat()  # 实际构建日期

CAT_NAMES = {'A': 'A · 理论与现实问题分析',
             'B': 'B · 学习科学与个人能力提升',
             'C': 'C · 考试方法论与命题研究',
             'D': 'D · 河南案例库',
             'W': 'W · 河南时政周报',
             'P': 'P · 政策文件摘要'}

REQUIRED_FIELDS = ['id', 'title', 'category', 'tags', 'related',
                   'evidence_level', 'sources', 'created', 'updated', 'status']
VALID_EVIDENCE = ['官方', '研究', '综合', '存疑']

# ---------- YAML 简易解析（够用即可：键: 值 / [a, b] 列表） ----------
try:
    import yaml as _yaml
    def parse_yaml(text):
        return _yaml.safe_load(text)
except ImportError:
    def parse_yaml(text):
        meta = {}
        for line in text.splitlines():
            if not line.strip() or ':' not in line:
                continue
            k, _, v = line.partition(':')
            v = v.strip()
            if v.startswith('[') and v.endswith(']'):
                inner = v[1:-1].strip()
                meta[k.strip()] = [x.strip() for x in inner.split(',')] if inner else []
            else:
                meta[k.strip()] = v
        return meta


def parse_topic(path):
    raw = open(path, encoding='utf-8').read()
    m = re.match(r'^---\n(.*?)\n---\n', raw, re.S)
    if not m:
        raise ValueError(f'{path}: 缺少 YAML 元数据头')
    meta = parse_yaml(m.group(1))
    body = raw[m.end():]
    # 提取快速知识卡
    card = re.search(r'##\s*⚡\s*快速知识卡\s*\n(.*?)\n##', body, re.S)
    card_text = card.group(1).strip() if card else ''
    return meta, body, card_text


def validate(meta, path, topic_ids, source_ids, body='', all_files=()):
    errs = []
    tid = str(meta.get('id', ''))
    if not re.match(r'^[A-Z]\d{2}$', tid):
        errs.append(f'id 非法: {tid}')
    if tid != os.path.basename(path)[:3]:
        errs.append(f'id 与文件名不一致: {tid} vs {os.path.basename(path)}')
    for f in REQUIRED_FIELDS:
        if f not in meta or meta[f] in (None, ''):
            errs.append(f'缺少字段 {f}')
    if meta.get('category') not in CAT_NAMES:
        errs.append(f'category 非法: {meta.get("category")}')
    ev = meta.get('evidence_level')
    if isinstance(ev, list):
        errs.append('evidence_level 必须是单个字符串（官方/研究/综合/存疑），不是列表')
    elif ev not in VALID_EVIDENCE:
        errs.append(f'evidence_level 非法: {ev}')
    for sid in meta.get('sources', []):
        if sid not in source_ids:
            errs.append(f'来源引用不存在: {sid}')
    for rid in meta.get('related', []):
        if rid not in topic_ids:
            errs.append(f'关联专题不存在: {rid}')
    # 字段类型校验：数组字段必须是列表
    for f in ['tags', 'related', 'sources']:
        if f in meta and not isinstance(meta[f], list):
            errs.append(f'{f} 必须是列表（如 [a, b]），当前为: {meta[f]!r}')
    if 'status' in meta and meta['status'] not in ('draft', 'reviewed'):
        errs.append(f'status 非法: {meta["status"]}')
    # 正文校验：来源 ID 兼容多种书写形式（[SXX]、[官方/SXX]、[研究/SXX]、[存疑·xx/SXX] 等）
    body_refs = set(re.findall(r'\[(?:[^[\]]*[/·])?(S[A-Z]\d{2})\]', body))
    for sid in body_refs - source_ids:
        errs.append(f'正文引用的来源不存在: [{sid}]')
    md_links = set(re.findall(r'\]\(([^)]+\.md)\)', body))
    for tgt in md_links - set(all_files):
        errs.append(f'正文链接指向不存在的专题文件: {tgt}')
    return errs


def build_html(topics, sources):
    data = {'generated': GENERATED_DATE, 'topics': topics, 'sources': sources}
    md_texts = {}
    for t in topics:
        p = os.path.join(TOPICS_DIR, t['file'])
        raw = open(p, encoding='utf-8').read()
        # 去掉 YAML 头，不在阅读页展示
        raw = re.sub(r'^---\n.*?\n---\n', '', raw, count=1, flags=re.S)
        # [[ID]] 双链 → JS 跳转；[标题](相对文件.md) → JS 跳转
        raw = re.sub(r'\[([^\]]+)\]\(([A-Z]\d\d)[^)]*\.md\)',
                     lambda m: f'[[{m.group(2)}]]', raw)
        md_texts[t['file']] = raw
    tpl_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'template.html')
    page = open(tpl_path, encoding='utf-8').read()
    js = json.dumps(data, ensure_ascii=False).replace('</', '<\\/')
    mds = json.dumps(md_texts, ensure_ascii=False).replace('</', '<\\/')
    page = page.replace('/*DATA*/null', js).replace('/*MDS*/null', mds)
    return page


def main():
    check_only = '--check' in sys.argv
    srcs = json.load(open(SOURCES_PATH, encoding='utf-8'))
    source_ids = {s['id'] for s in srcs}
    files = sorted(glob.glob(os.path.join(TOPICS_DIR, '*.md')))
    # 先收集全部专题 ID（校验 related 用），并检测重复
    topic_ids, dup_ids = set(), []
    for f in files:
        meta, _, _ = parse_topic(f)
        tid = str(meta.get('id'))
        if tid in topic_ids:
            dup_ids.append(f'{tid}（{os.path.basename(f)}）')
        topic_ids.add(tid)
    if dup_ids:
        print('[ERROR] 重复专题 ID:', '；'.join(dup_ids))
        print('校验未通过，未写出文件。')
        sys.exit(1)
    dup_srcs = [s['id'] for s in srcs if [x['id'] for x in srcs].count(s['id']) > 1]
    if dup_srcs:
        print('[ERROR] 重复来源 ID:', '；'.join(sorted(set(dup_srcs))))
        print('校验未通过，未写出文件。')
        sys.exit(1)
    topics, had_error = [], False
    for f in files:
        meta, body, card = parse_topic(f)
        errs = validate(meta, f, topic_ids, source_ids, body, [os.path.basename(x) for x in files])
        if errs:
            had_error = True
            print(f'[ERROR] {os.path.basename(f)}:')
            for e in errs:
                print('   -', e)
            continue
        card_cn = len(re.sub(r'[^\u4e00-\u9fff]', '', card))
        if not (140 <= card_cn <= 260):
            print(f'[WARN] {meta["id"]} 快速知识卡 {card_cn} 字（建议 150–250）')
        topics.append({'id': str(meta['id']), 'title': str(meta['title']),
                       'category': meta['category'], 'tags': meta.get('tags', []),
                       'related': meta.get('related', []),
                       'evidence_level': meta['evidence_level'],
                       'sources': meta.get('sources', []),
                       'created': str(meta['created']), 'updated': str(meta['updated']),
                       'status': meta['status'], 'file': os.path.basename(f),
                       'card': card})
    if had_error:
        print('校验未通过，未写出文件。')
        sys.exit(1)
    print(f'校验通过：{len(topics)} 个专题，{len(srcs)} 条来源')
    if check_only:
        return
    os.makedirs(os.path.dirname(INDEX_PATH), exist_ok=True)
    json.dump(topics, open(INDEX_PATH, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)
    os.makedirs(SITE_DIR, exist_ok=True)
    html = build_html(topics, srcs)
    open(os.path.join(SITE_DIR, 'index.html'), 'w', encoding='utf-8').write(html)
    # GitHub Pages 从 docs/ 发布，同步一份
    DOCS_DIR = os.path.join(ROOT, 'docs')
    os.makedirs(DOCS_DIR, exist_ok=True)
    open(os.path.join(DOCS_DIR, 'index.html'), 'w', encoding='utf-8').write(html)
    open(os.path.join(DOCS_DIR, '.nojekyll'), 'w', encoding='utf-8').write('')
    print(f'已生成: {os.path.relpath(INDEX_PATH, ROOT)}')
    print(f'已生成: {os.path.relpath(os.path.join(SITE_DIR, "index.html"), ROOT)}')
    print(f'已同步: docs/index.html（GitHub Pages）')

if __name__ == '__main__':
    main()
