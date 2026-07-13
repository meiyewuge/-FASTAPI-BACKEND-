#!/usr/bin/env python3.11
# -*- coding: utf-8 -*-
"""
WUGE Search Router P0 — 每日情报管线 V2
模式:
  默认: 搜索 → 写入incoming (不触发ingest，由cron wrapper分步执行)
  --search-only: 只搜索+写入 (默认行为)
  --verify-only: 只9080验收
  --dry-run: 预览模式，写入/tmp
"""
import os, sys, json, hashlib, datetime, asyncio, re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from search_router.config import SearchRouterConfig
from search_router.models.search_request import SearchRequest, TaskType
from search_router.router import SearchRouter

KNOWLEDGE_BASE = '/opt/knowledge-search'
INCOMING = f'{KNOWLEDGE_BASE}/incoming'
TOKEN_FILE = '/etc/knowledge-search.env'
SEARCH_API = 'http://127.0.0.1:9080/search'
TODAY = datetime.datetime.now().strftime('%Y%m%d')
TODAY_FULL = datetime.datetime.now().strftime('%Y-%m-%d')
LOG_DIR = '/var/log/wuge-search-router'
REPORT_DIR = '/var/log/wuge-search-router/reports'

DIMENSIONS = [
    {'name': '品牌与产品', 'query': '美业 品牌 产品 新锐 趋势', 'task_type': TaskType.CHINESE_INDUSTRY_NEWS},
    {'name': '数字化与AI', 'query': '美业 AI 工具 数字化 趋势', 'task_type': TaskType.GLOBAL_AI_TOOLS},
    {'name': '政策法规', 'query': '美业 政策 法规 合规 NMPA', 'task_type': TaskType.OFFICIAL_DOCS},
    {'name': '门店增长', 'query': '美容院 经营 门店 增长 获客', 'task_type': TaskType.CHINESE_INDUSTRY_NEWS},
    {'name': '行业资本', 'query': '美业 趋势 融资 并购 上市', 'task_type': TaskType.TECHNICAL_RESEARCH},
    {'name': '抖音私域', 'query': '美业 抖音 私域 直播 本地生活', 'task_type': TaskType.CHINESE_INDUSTRY_NEWS},
]

SOURCE_TIER = {
    'nmpa.gov.cn': 'A', 'samr.gov.cn': 'A', 'fda.gov': 'A', 'europa.eu': 'A',
    'pinguan.com': 'B', '.cbo.cn': 'B', 'beauty.c2cc.cn': 'B', 'businessoffashion.com': 'B',
    'wwd.com': 'B', 'cosmeticsdesign.com': 'B',
    'shiseido.com': 'C', 'loreal.com': 'C', 'estee.com': 'C',
    'mp.weixin.qq.com': 'D', 'toutiao.com': 'D',
}
TIER_MIN_INGEST = {'A': 0.3, 'B': 0.4, 'C': 0.5, 'D': 0.7, 'E': 1.0}


def classify_source(url):
    for domain, tier in SOURCE_TIER.items():
        if domain in url:
            return tier
    return 'C'


def card_to_md(card, dim_name, idx):
    object_id = f'SR_{TODAY}_{dim_name[:2]}_{str(idx).zfill(3)}'
    tier = classify_source(card.url)
    is_glm_ref = card.url.startswith('glm-search://')
    can_ingest = (
        card.confidence_score >= TIER_MIN_INGEST.get(tier, 0.5)
        and tier != 'E' and card.ingest_status != 'rejected'
    )
    risk_tags = []
    if hasattr(card, 'risk_category') and card.risk_category in ('legal_policy', 'medical'):
        risk_tags.append(card.risk_category)
    if is_glm_ref:
        risk_tags.append('glm_ref_no_url')
    review_status = 'pending_review' if can_ingest else 'auto_discard'
    title_slug = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fff]', '_', card.title)[:40]
    filename = f'{object_id}_{title_slug}.md'
    summary = getattr(card, 'summary', '') or getattr(card, 'evidence_excerpt', '') or '请访问链接查看完整内容'
    content = f'''---
## object_id {object_id}
## source_type search_router_intel
## review_status {review_status}
## default_recall {str(can_ingest).lower()}
## priority {5 if can_ingest else 8}
## frontline_sales_default false
## dimension {dim_name}
## confidence_score {card.confidence_score:.2f}
## source_tier {tier}
## risk_tags {",".join(risk_tags) if risk_tags else "none"}
## ingest_status {card.ingest_status}

## title
{card.title}

## source_url
{card.url}

## source_name
{card.source}

## publish_time
{getattr(card, "publish_time", "unknown") or "unknown"}

## summary
{summary}

## key_points
- 来源：{card.source}
- 维度：{dim_name}
- 信源等级：{tier}
- 置信度：{card.confidence_score:.2f}
- 建议动作：{card.suggested_action}
- 抓取时间：{TODAY_FULL}

## risk_control
{"高风险需人工审核" if risk_tags else "pending_review禁止一线调用"}

---
# {card.title}

{summary}

来源：{card.source} | 置信度：{card.confidence_score:.2f} | 信源等级：{tier}
'''
    return filename, content, object_id


def get_token():
    try:
        for line in open(TOKEN_FILE):
            if 'API_TOKEN' in line and '=' in line:
                return line.strip().split('=', 1)[1].strip()
    except:
        pass
    return ''


async def do_search(max_results=5, dry_run=False):
    """Step 1: 搜索 + 写入incoming"""
    os.makedirs(INCOMING, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)

    config = SearchRouterConfig.from_env()
    router = SearchRouter(config=config)

    print(f'【搜索阶段】{TODAY_FULL}')
    print(f'mode={"DRY-RUN" if dry_run else "正式"} dry_run={config.dry_run} glm={config.provider_glm_search_enabled}\n')

    all_cards = []
    dim_stats = []

    for dim in DIMENSIONS:
        print(f'  [{dim["name"]}] ', end='', flush=True)
        request = SearchRequest(query=dim['query'], task_type=dim['task_type'], max_results=max_results)
        try:
            result = await router.search(request)
            cards = result.cards or []
            print(f'P={result.provider_used} N={len(cards)} Cost={result.total_cost}')
            for card in cards:
                card._dimension = dim['name']
            all_cards.extend(cards)
            dim_stats.append({'dimension': dim['name'], 'provider': result.provider_used,
                              'cards': len(cards), 'cost': result.total_cost, 'success': result.success})
        except Exception as e:
            print(f'FAIL: {e}')
            dim_stats.append({'dimension': dim['name'], 'provider': 'error', 'cards': 0, 'cost': 0, 'success': False})

    target_dir = '/tmp/wuge_pipeline_preview' if dry_run else INCOMING
    os.makedirs(target_dir, exist_ok=True)

    counter = 1
    written = []
    ingest_candidates = 0

    for card in all_cards:
        dim_name = getattr(card, '_dimension', 'unknown')
        filename, content, object_id = card_to_md(card, dim_name, counter)
        with open(os.path.join(target_dir, filename), 'w', encoding='utf-8') as f:
            f.write(content)
        can_ingest = card.confidence_score >= 0.5 and card.ingest_status != 'rejected'
        if can_ingest:
            ingest_candidates += 1
        written.append({'filename': filename, 'object_id': object_id, 'dimension': dim_name,
                        'source': card.source, 'confidence': card.confidence_score,
                        'ingest': card.ingest_status, 'can_ingest': can_ingest,
                        'title': card.title[:60], 'url': card.url[:80]})
        counter += 1

    print(f'\n写入 {len(written)} MD → {target_dir}')
    print(f'入库候选: {ingest_candidates}')

    # 报告
    report = {'date': TODAY_FULL, 'mode': 'dry_run' if dry_run else 'production',
              'total_cards': len(all_cards), 'ingest_candidates': ingest_candidates,
              'dimensions': dim_stats, 'files': written}
    with open(os.path.join(REPORT_DIR, f'pipeline_{TODAY}.json'), 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    return len(written), ingest_candidates


def do_verify():
    """Step 2: 9080验收"""
    import requests
    token = get_token()
    if not token:
        print('Token未配置，跳过验收')
        return

    report_path = os.path.join(REPORT_DIR, f'pipeline_{TODAY}.json')
    if not os.path.exists(report_path):
        print('报告不存在，跳过验收')
        return

    with open(report_path, 'r') as f:
        report = json.load(f)

    verified = 0
    print(f'【验收阶段】验证 {len(report.get("files",[]))} 条...')
    for w in report.get('files', []):
        if not w.get('can_ingest'):
            continue
        try:
            r = requests.post(SEARCH_API, json={'query': w['object_id'], 'top_k': 3},
                              headers={'Authorization': f'Bearer {token}'}, timeout=10)
            ok = r.status_code == 200 and bool(r.json().get('results'))
            if ok:
                verified += 1
            w['verified'] = ok
        except:
            w['verified'] = False

    report['verified'] = verified
    with open(report_path, 'w') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f'验收通过: {verified}/{len([w for w in report.get("files",[]) if w.get("can_ingest")])}')


def main():
    args = sys.argv[1:]
    dry_run = '--dry-run' in args
    verify_only = '--verify-only' in args
    max_results = 5
    for arg in args:
        if arg.startswith('--max-results='):
            max_results = int(arg.split('=')[1])

    if verify_only:
        do_verify()
    else:
        n, v = asyncio.run(do_search(max_results=max_results, dry_run=dry_run))
        sys.exit(0 if n > 0 else 1)


if __name__ == '__main__':
    main()
