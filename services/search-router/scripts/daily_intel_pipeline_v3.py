#!/usr/bin/env python3.11
# -*- coding: utf-8 -*-
"""
WUGE Search Router P0.1 — 每日情报管线 V3 (NEURAL_OS_INGEST_GATE_PATCH)
定位：阿里云美业AI神经中枢 L1感知层 + 情报补给层 + 知识候选生成器

核心改造：
  1. 情报卡frontmatter增加neural_os全套字段
  2. 产物默认进入candidate_review_pool，不进正式主库
  3. 分流规则：按维度建议target_kb
  4. default_recall=false, default_retrievable=false

模式:
  --search-only: 搜索+写入候选池(默认)
  --verify-only: 9080验收
  --dry-run: 预览模式，写入/tmp
  --review-approve <object_id>: 审核通过→移入incoming→可入库
  --review-reject <object_id>: 审核拒绝→移入rejected
  --review-list: 列出待审核候选
"""
import os, sys, json, hashlib, datetime, asyncio, re, shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from search_router.config import SearchRouterConfig
from search_router.models.search_request import SearchRequest, TaskType
from search_router.router import SearchRouter

KNOWLEDGE_BASE = '/opt/knowledge-search'
INCOMING = f'{KNOWLEDGE_BASE}/incoming'
CANDIDATE_POOL = f'{KNOWLEDGE_BASE}/knowledge_workflow/candidate_review_pool'
CANDIDATE_PENDING = f'{CANDIDATE_POOL}/pending'
CANDIDATE_APPROVED = f'{CANDIDATE_POOL}/approved'
CANDIDATE_REJECTED = f'{CANDIDATE_POOL}/rejected'
TOKEN_FILE = '/etc/knowledge-search.env'
SEARCH_API = 'http://127.0.0.1:9080/search'
CANDIDATES_API = 'http://127.0.0.1:9080/search_candidates'
TODAY = datetime.datetime.now().strftime('%Y%m%d')
TODAY_FULL = datetime.datetime.now().strftime('%Y-%m-%d')
LOG_DIR = '/var/log/wuge-search-router'
REPORT_DIR = '/var/log/wuge-search-router/reports'

# === 6维度搜索配置 ===
DIMENSIONS = [
    {'name': '品牌与产品', 'query': '美业 品牌 产品 新锐 趋势', 'task_type': TaskType.CHINESE_INDUSTRY_NEWS},
    {'name': '数字化与AI', 'query': '美业 AI 工具 数字化 趋势', 'task_type': TaskType.GLOBAL_AI_TOOLS},
    {'name': '政策法规',   'query': '美业 政策 法规 合规 NMPA', 'task_type': TaskType.OFFICIAL_DOCS},
    {'name': '门店增长',   'query': '美容院 经营 门店 增长 获客', 'task_type': TaskType.CHINESE_INDUSTRY_NEWS},
    {'name': '行业资本',   'query': '美业 趋势 融资 并购 上市', 'task_type': TaskType.TECHNICAL_RESEARCH},
    {'name': '抖音私域',   'query': '美业 抖音 私域 直播 本地生活', 'task_type': TaskType.CHINESE_INDUSTRY_NEWS},
]

# === 信源分级 ===
SOURCE_TIER = {
    'nmpa.gov.cn': 'A', 'samr.gov.cn': 'A', 'fda.gov': 'A', 'europa.eu': 'A',
    'pinguan.com': 'B', '.cbo.cn': 'B', 'beauty.c2cc.cn': 'B', 'businessoffashion.com': 'B',
    'wwd.com': 'B', 'cosmeticsdesign.com': 'B',
    'shiseido.com': 'C', 'loreal.com': 'C', 'estee.com': 'C',
    'mp.weixin.qq.com': 'D', 'toutiao.com': 'D',
}
TIER_MIN_INGEST = {'A': 0.3, 'B': 0.4, 'C': 0.5, 'D': 0.7, 'E': 1.0}

# === 分流规则：维度→建议目标库 ===
DIMENSION_KB_MAP = {
    '品牌与产品': ['DEFAULT_MAIN_KB', 'WUGE_IP_CONTENT_FACTORY'],
    '数字化与AI': ['COMMON_METHOD_KB'],
    '政策法规':   ['RISK_CASE_KB', 'DEFAULT_MAIN_KB'],
    '门店增长':   ['STORE_MANAGER_WORKBENCH', 'COMMON_METHOD_KB'],
    '行业资本':   ['DEFAULT_MAIN_KB'],
    '抖音私域':   ['WUGE_IP_CONTENT_FACTORY', 'RISK_CASE_KB'],
}

# === 维度→风险等级 ===
DIMENSION_RISK = {
    '品牌与产品': 'low',
    '数字化与AI': 'low',
    '政策法规':   'high',
    '门店增长':   'medium',
    '行业资本':   'medium',
    '抖音私域':   'medium',
}


def classify_source(url):
    for domain, tier in SOURCE_TIER.items():
        if domain in url:
            return tier
    return 'C'


def card_to_md(card, dim_name, idx):
    """生成含neural_os全套字段的情报卡MD"""
    object_id = f'SR_{TODAY}_{dim_name[:2]}_{str(idx).zfill(3)}'
    tier = classify_source(card.url)
    is_glm_ref = card.url.startswith('glm-search://')
    can_ingest = (
        card.confidence_score >= TIER_MIN_INGEST.get(tier, 0.5)
        and tier != 'E' and card.ingest_status != 'rejected'
    )

    # 风险标签
    risk_tags = []
    if hasattr(card, 'risk_category') and card.risk_category in ('legal_policy', 'medical'):
        risk_tags.append(card.risk_category)
    if is_glm_ref:
        risk_tags.append('glm_ref_no_url')

    # neural_os 核心字段
    risk_level = DIMENSION_RISK.get(dim_name, 'low')
    if risk_tags:
        if 'legal_policy' in risk_tags or 'medical' in risk_tags:
            risk_level = 'high'
        elif 'glm_ref_no_url' in risk_tags:
            risk_level = 'medium'

    need_fact_check = risk_level in ('high', 'medium') or tier in ('D', 'E')
    target_kb = DIMENSION_KB_MAP.get(dim_name, ['DEFAULT_MAIN_KB'])

    # 医美/功效/法规敏感必须人工审核
    require_manual_review = (
        risk_level == 'high'
        or 'legal_policy' in risk_tags
        or 'medical' in risk_tags
        or any(kw in card.title for kw in ['医美', '功效', '注射', '手术', '处方', '药品'])
    )

    title_slug = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fff]', '_', card.title)[:40]
    filename = f'{object_id}_{title_slug}.md'
    summary = getattr(card, 'summary', '') or getattr(card, 'evidence_excerpt', '') or '请访问链接查看完整内容'

    # === neural_os frontmatter ===
    content = f'''---
## object_id {object_id}
## source_channel search_router
## neural_os_layer L1_external_intelligence
## target_pipeline knowledge_workflow
## review_status pending_review
## candidate_for_ingest {str(can_ingest).lower()}
## default_recall false
## default_retrievable false
## source_tier {tier}
## risk_level {risk_level}
## need_fact_check {str(need_fact_check).lower()}
## require_manual_review {str(require_manual_review).lower()}
## confidence_score {card.confidence_score:.2f}
## dimension {dim_name}
## ingest_status {card.ingest_status}
## risk_tags {",".join(risk_tags) if risk_tags else "none"}
## target_kb_suggestion {",".join(target_kb)}
## allowed_usage audit,trend_watch,candidate_review
## not_allowed_usage final_advice,customer_facing,default_business_answer
## priority {5 if can_ingest else 8}
## frontline_sales_default false

## title
{card.title}

## source_url
{card.url}

## source_name
{card.source}

## publish_time
{getattr(card, "publish_time", "unknown") or "unknown"}

## fetched_at
{TODAY_FULL}

## summary
{summary}

## key_points
- 来源：{card.source}
- 维度：{dim_name}
- 信源等级：{tier}
- 置信度：{card.confidence_score:.2f}
- 风险等级：{risk_level}
- 人工审核：{"是" if require_manual_review else "否"}
- 建议目标库：{",".join(target_kb)}
- 建议动作：{card.suggested_action}

## risk_control
{"高风险-必须人工审核-不得自动入库" if require_manual_review else "pending_review-禁止一线调用-候选池隔离"}

## neural_os_routing
layer: L1_external_intelligence
pipeline: knowledge_workflow
flow: search_router -> candidate_review_pool -> review -> target_kb
recall_policy: default_recall=false until review_status=approved
usage_policy: candidate_review_only, not for business default answer

---

# {card.title}

{summary}

来源：{card.source} | 置信度：{card.confidence_score:.2f} | 信源等级：{tier} | 风险：{risk_level}
'''
    return filename, content, object_id, can_ingest, risk_level, target_kb


def get_token():
    try:
        for line in open(TOKEN_FILE):
            if 'API_TOKEN' in line and '=' in line:
                return line.strip().split('=', 1)[1].strip()
    except:
        pass
    return ''


async def do_search(max_results=5, dry_run=False):
    """Step 1: 搜索 + 写入候选池(非正式主库)"""
    os.makedirs(CANDIDATE_PENDING, exist_ok=True)
    os.makedirs(CANDIDATE_APPROVED, exist_ok=True)
    os.makedirs(CANDIDATE_REJECTED, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)

    config = SearchRouterConfig.from_env()
    router = SearchRouter(config=config)

    print(f'【搜索阶段·候选池写入】{TODAY_FULL}')
    print(f'定位: 阿里云AI神经中枢 L1感知层 | 产物: 候选卡(非正式主库)')
    print(f'mode={"DRY-RUN" if dry_run else "正式"} glm={config.provider_glm_search_enabled}\n')

    all_cards = []
    dim_stats = []

    # P0.1A 治理：通过环境变量跳过指定维度（不改DIMENSIONS定义）
    _skip_dims = set(d.strip() for d in os.environ.get('SKIP_DIMENSIONS', '').split(',') if d.strip())
    if _skip_dims:
        print(f'  [SKIP_DIMENSIONS] {",".join(_skip_dims)}')

    for dim in DIMENSIONS:
        if dim['name'] in _skip_dims:
            print(f'  [{dim["name"]}] SKIPPED (SKIP_DIMENSIONS)')
            dim_stats.append({'dimension': dim['name'], 'provider': 'skipped', 'cards': 0, 'cost': 0, 'success': True, 'skipped': True})
            continue
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

    target_dir = '/tmp/wuge_pipeline_preview' if dry_run else CANDIDATE_PENDING
    os.makedirs(target_dir, exist_ok=True)

    counter = 1
    written = []
    ingest_candidates = 0
    manual_review_required = 0
    risk_high = 0
    kb_dist = {}

    for card in all_cards:
        dim_name = getattr(card, '_dimension', 'unknown')
        filename, content, object_id, can_ingest, risk_level, target_kb = card_to_md(card, dim_name, counter)
        with open(os.path.join(target_dir, filename), 'w', encoding='utf-8') as f:
            f.write(content)
        if can_ingest:
            ingest_candidates += 1
        if risk_level == 'high':
            risk_high += 1
        if 'legal_policy' in str(getattr(card, 'risk_category', '')) or 'medical' in str(getattr(card, 'risk_category', '')):
            manual_review_required += 1
        for kb in target_kb:
            kb_dist[kb] = kb_dist.get(kb, 0) + 1
        written.append({'filename': filename, 'object_id': object_id, 'dimension': dim_name,
                        'source': card.source, 'confidence': card.confidence_score,
                        'ingest': card.ingest_status, 'can_ingest': can_ingest,
                        'risk_level': risk_level, 'target_kb': target_kb,
                        'title': card.title[:60], 'url': card.url[:80]})
        counter += 1

    print(f'\n写入 {len(written)} 候选卡 → {target_dir}')
    print(f'入库候选: {ingest_candidates} | 高风险: {risk_high} | 需人工审核: {manual_review_required}')
    print(f'目标库分布: {json.dumps(kb_dist, ensure_ascii=False)}')
    print(f'⚠️ 所有候选卡 default_recall=false, 不会进入业务默认答案')

    report = {'date': TODAY_FULL, 'mode': 'dry_run' if dry_run else 'production',
              'patch': 'P0.1_NEURAL_OS_INGEST_GATE',
              'total_cards': len(all_cards), 'ingest_candidates': ingest_candidates,
              'risk_high': risk_high, 'manual_review_required': manual_review_required,
              'kb_distribution': kb_dist,
              'neural_os_layer': 'L1_external_intelligence',
              'target_pipeline': 'knowledge_workflow',
              'isolation': 'candidate_review_pool_not_main_kb',
              'dimensions': dim_stats, 'files': written}
    with open(os.path.join(REPORT_DIR, f'pipeline_{TODAY}.json'), 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    return len(written), ingest_candidates


def do_verify():
    """Step 2: 9080验收(只验正式库，候选池不走9080)"""
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

    # 候选池验收：通过9080 /search_candidates端点
    verified = 0
    candidate_files = [w for w in report.get('files', []) if w.get('can_ingest')]
    print(f'【候选池验收】验证 {len(candidate_files)} 条...')

    for w in candidate_files:
        try:
            r = requests.post(CANDIDATES_API, json={'query': w['object_id'], 'top_k': 3},
                              headers={'Authorization': f'Bearer {token}'}, timeout=10)
            ok = r.status_code == 200
            if ok:
                verified += 1
            w['verified'] = ok
        except:
            w['verified'] = False

    report['candidate_verified'] = verified
    with open(report_path, 'w') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f'候选池验证通过: {verified}/{len(candidate_files)}')


def do_review_list():
    """列出待审核候选"""
    pending_dir = CANDIDATE_PENDING
    if not os.path.isdir(pending_dir):
        print('候选池为空')
        return
    files = sorted([f for f in os.listdir(pending_dir) if f.endswith('.md')])
    if not files:
        print('无待审核候选')
        return
    print(f'【待审核候选】共 {len(files)} 条\n')
    for f in files:
        path = os.path.join(pending_dir, f)
        with open(path, 'r', encoding='utf-8') as fh:
            lines = fh.readlines()[:30]
        meta = {}
        for line in lines:
            if line.startswith('## '):
                parts = line.strip().split(' ', 2)
                if len(parts) >= 3:
                    meta[parts[1]] = parts[2]
        obj_id = meta.get('object_id', '?')
        risk = meta.get('risk_level', '?')
        dim = meta.get('dimension', '?')
        kb = meta.get('target_kb_suggestion', '?')
        title_m = [l for l in lines if l.strip() and not l.startswith('#') and not l.startswith('##') and len(l.strip()) > 10]
        title = title_m[0].strip()[:50] if title_m else meta.get('title', '?')[:50]
        manual = meta.get('require_manual_review', 'false')
        flag = '🔴' if manual == 'true' else ('🟡' if risk == 'medium' else '🟢')
        print(f'{flag} {obj_id} | {dim} | risk={risk} | KB={kb} | {title}')


def do_review_approve(object_id):
    """审核通过：候选→incoming(可入库)"""
    src = None
    for f in os.listdir(CANDIDATE_PENDING):
        if f.startswith(object_id) and f.endswith('.md'):
            src = os.path.join(CANDIDATE_PENDING, f)
            break
    if not src:
        print(f'未找到候选: {object_id}')
        return

    # 更新frontmatter
    with open(src, 'r', encoding='utf-8') as f:
        content = f.read()
    content = content.replace('## review_status pending_review', '## review_status approved')
    content = content.replace('## default_recall false', '## default_recall true')
    content = content.replace('## default_retrievable false', '## default_retrievable true')
    content = content.replace('## candidate_for_ingest true', '## candidate_for_ingest true')

    # 写入approved
    approved_path = os.path.join(CANDIDATE_APPROVED, os.path.basename(src))
    with open(approved_path, 'w', encoding='utf-8') as f:
        f.write(content)

    # 复制到incoming(可入库)
    shutil.copy2(approved_path, os.path.join(INCOMING, os.path.basename(src)))

    # 删除pending
    os.remove(src)
    print(f'✅ {object_id} 审核通过 → approved + incoming(可入库)')


def do_review_reject(object_id):
    """审核拒绝：候选→rejected"""
    src = None
    for f in os.listdir(CANDIDATE_PENDING):
        if f.startswith(object_id) and f.endswith('.md'):
            src = os.path.join(CANDIDATE_PENDING, f)
            break
    if not src:
        print(f'未找到候选: {object_id}')
        return

    with open(src, 'r', encoding='utf-8') as f:
        content = f.read()
    content = content.replace('## review_status pending_review', '## review_status rejected')
    content = content.replace('## candidate_for_ingest true', '## candidate_for_ingest false')

    rejected_path = os.path.join(CANDIDATE_REJECTED, os.path.basename(src))
    with open(rejected_path, 'w', encoding='utf-8') as f:
        f.write(content)

    os.remove(src)
    print(f'❌ {object_id} 审核拒绝 → rejected')


def main():
    args = sys.argv[1:]
    dry_run = '--dry-run' in args
    verify_only = '--verify-only' in args
    max_results = 5
    for arg in args:
        if arg.startswith('--max-results='):
            max_results = int(arg.split('=')[1])

    if '--review-list' in args:
        do_review_list()
    elif '--review-approve' in args:
        idx = args.index('--review-approve')
        if idx + 1 < len(args):
            do_review_approve(args[idx + 1])
        else:
            print('用法: --review-approve <object_id>')
    elif '--review-reject' in args:
        idx = args.index('--review-reject')
        if idx + 1 < len(args):
            do_review_reject(args[idx + 1])
        else:
            print('用法: --review-reject <object_id>')
    elif verify_only:
        do_verify()
    else:
        n, v = asyncio.run(do_search(max_results=max_results, dry_run=dry_run))
        sys.exit(0 if n > 0 else 1)


if __name__ == '__main__':
    main()
