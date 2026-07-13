#!/usr/bin/env python3.11
# -*- coding: utf-8 -*-
"""升级候选池中旧格式SR_卡的frontmatter为neural_os格式"""
import os, re, glob

CANDIDATE_PENDING = '/opt/knowledge-search/knowledge_workflow/candidate_review_pool/pending'
DIMENSION_KB_MAP = {
    '品牌': ['DEFAULT_MAIN_KB', 'WUGE_IP_CONTENT_FACTORY'],
    '数字': ['COMMON_METHOD_KB'],
    '政策': ['RISK_CASE_KB', 'DEFAULT_MAIN_KB'],
    '门店': ['STORE_MANAGER_WORKBENCH', 'COMMON_METHOD_KB'],
    '行业': ['DEFAULT_MAIN_KB'],
    '抖音': ['WUGE_IP_CONTENT_FACTORY', 'RISK_CASE_KB'],
}
DIMENSION_RISK = {
    '品牌': 'low', '数字': 'low', '政策': 'high',
    '门店': 'medium', '行业': 'medium', '抖音': 'medium',
}

def get_dim_from_filename(fname):
    for key in DIMENSION_KB_MAP:
        if key in fname:
            return key
    return None

def upgrade_file(fpath):
    with open(fpath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 如果已有neural_os_layer字段，跳过
    if '## neural_os_layer' in content:
        return False
    
    dim = get_dim_from_filename(os.path.basename(fpath))
    if not dim:
        dim = '品牌'
    
    target_kb = ','.join(DIMENSION_KB_MAP.get(dim, ['DEFAULT_MAIN_KB']))
    risk = DIMENSION_RISK.get(dim, 'low')
    
    # 添加neural_os字段（在review_status行后）
    insertions = [
        ('## review_status', 
         '## review_status pending_review\n## source_channel search_router\n## neural_os_layer L1_external_intelligence\n## target_pipeline knowledge_workflow'),
        ('## default_recall true',
         '## default_recall false'),
        ('## default_retrievable false' if '## default_retrievable' not in content else None,
         None),
    ]
    
    # 添加缺失字段
    if '## source_channel' not in content:
        content = content.replace('## review_status', '## source_channel search_router\n## review_status')
    if '## neural_os_layer' not in content:
        content = content.replace('## source_channel search_router', '## source_channel search_router\n## neural_os_layer L1_external_intelligence')
    if '## target_pipeline' not in content:
        content = content.replace('## neural_os_layer L1_external_intelligence', '## neural_os_layer L1_external_intelligence\n## target_pipeline knowledge_workflow')
    if '## candidate_for_ingest' not in content:
        content = content.replace('## target_pipeline knowledge_workflow', '## target_pipeline knowledge_workflow\n## candidate_for_ingest true')
    
    # 强制default_recall=false（候选池禁止直接召回）
    content = content.replace('## default_recall true', '## default_recall false')
    
    if '## default_retrievable' not in content:
        content = content.replace('## default_recall false', '## default_recall false\n## default_retrievable false')
    else:
        content = content.replace('## default_retrievable true', '## default_retrievable false')
    
    if '## risk_level' not in content:
        content = content.replace('## default_retrievable false', '## default_retrievable false\n## risk_level ' + risk)
    
    if '## need_fact_check' not in content:
        need_fc = 'true' if risk in ('high', 'medium') else 'false'
        content = content.replace('## risk_level ' + risk, '## risk_level ' + risk + '\n## need_fact_check ' + need_fc)
    
    if '## require_manual_review' not in content:
        manual = 'true' if risk == 'high' else 'false'
        content = content.replace('## need_fact_check', '## require_manual_review ' + manual + '\n## need_fact_check')
    
    if '## target_kb_suggestion' not in content:
        content = content.replace('## risk_tags', '## target_kb_suggestion ' + target_kb + '\n## risk_tags')
    
    if '## allowed_usage' not in content:
        content = content.replace('## frontline_sales_default false', '## allowed_usage audit,trend_watch,candidate_review\n## not_allowed_usage final_advice,customer_facing,default_business_answer\n## frontline_sales_default false')
    
    if '## fetched_at' not in content:
        content = content.replace('## publish_time', '## fetched_at 2026-07-01\n## publish_time')
    
    with open(fpath, 'w', encoding='utf-8') as f:
        f.write(content)
    return True

count = 0
for fpath in glob.glob(os.path.join(CANDIDATE_PENDING, '*.md')):
    if upgrade_file(fpath):
        count += 1

print(f'Upgraded {count} candidate cards with neural_os frontmatter')
