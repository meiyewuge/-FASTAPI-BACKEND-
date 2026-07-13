#!/bin/bash
# WUGE Search Router P0.1 — 每日情报管线 cron wrapper
# 定位：阿里云AI神经中枢 L1感知层
# 流程：搜索→候选池(非主库) → 验收
# P0.1A治理：SKIP_DIMENSIONS控制哪些维度不跑（环境变量，不改DIMENSIONS定义）

set -e
PYTHON=/usr/bin/python3.11
PIPELINE=/opt/wuge-labs/search-router-production/scripts/daily_intel_pipeline_v3.py
LOG=/var/log/wuge-search-router/cron.log
REPORT_DIR=/var/log/wuge-search-router/reports

mkdir -p /var/log/wuge-search-router/reports

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === Pipeline V3 P0.1 Start ===" >> $LOG

# P0.1A 治理：暂停抖音私域(广告率75%)和行业资本旧query(跨维度重复42%)
# 等P0.2改写/重构后恢复
export SKIP_DIMENSIONS="抖音私域,行业资本"

# Step 1: 搜索 → 写入候选池
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Step1: Search → Candidate Pool (SKIP_DIMENSIONS=$SKIP_DIMENSIONS)" >> $LOG
$PYTHON $PIPELINE --search-only --max-results=3 >> $LOG 2>&1 || true

# 注意：候选池中的内容不自动进入正式主库
# 需要人工审核通过后才移入incoming → ingest → data/
# 自动入库已禁用，防止候选内容污染正式库

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === Pipeline V3 P0.1 Done ===" >> $LOG
