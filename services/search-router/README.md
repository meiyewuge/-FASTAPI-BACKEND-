# WUGE Search Router P0 — T5 入口层

> 基于《WUGE Search Router P0 代码实现任务拆分 V0.1.1》
> 在 **T4 V0.1.1 完整基线**（T1+T2A+T2B+T3+T4，491/491 通过）之上增量开发。

## 版本

- **任务**: T5 — 入口层（P0 最终层）
- **版本**: V0.1.0
- **日期**: 2026-06-27
- **状态**: 待 ChatGPT 审核
- **基线**: T4 V0.1.1（SHA256: `0d566b0bdfb76f4aa1341b095abc2e9c98e0593d323395d0adfd29c6b332b4f4`）

## T5 基线说明

| 层级 | 来源 | 用例数 | 说明 |
|------|------|--------|------|
| T1 | 智谱 T1 V0.1.1 | 82 | config / logger / models / BaseProviderAdapter / MockProviderAdapter |
| T2A | 克洛德 T2A V0.1.1 | 72 | Bocha / GLM / Tavily Adapter 骨架 |
| T2B | 克洛德 T2B V0.1.1 | 103 | ProviderFactory / ProviderManager / CostTracker / RetryPolicy / 三锁 / F1·F2·F3 |
| T3 | 智谱 T3 V0.1.1 | 155 | ResultMerger / DedupManager / SearchResultMapper / industry 4 模块 |
| T4 | 智谱 T4 V0.1.1 | 79 | GLMEnhancer / CandidatePool / DualReviewGate |
| **T5** | **智谱 T5（本次）** | **35** | **SearchRouter 主路由 / CLI / E2E 测试** |
| **合计** | | **526** | |

## T5 新增模块

| 文件 | 说明 |
|------|------|
| `search_router/router.py` | SearchRouter — 主路由入口，编排全链路 |
| `examples/run_single_search.py` | CLI — 单次搜索 |
| `examples/run_daily_intel.py` | CLI — 每日情报 |
| `tests/test_router_e2e.py` | 21 项 E2E 测试 |
| `tests/test_enhancer_e2e.py` | 14 项三锁端到端测试 |

## 主路由流程

```
SearchRequest
    ↓
CostTracker.pre_check()
    ↓
ProviderFactory → MockProviderAdapter (dry_run=true)
    ↓
Provider.search() → SearchResponse
    ↓
ResultMerger.merge(results) → 4层去重
    ↓
DedupManager.check_batch(urls) → 7天历史去重
    ↓
map_batch(results) → IndustryIntelligenceCard 列表
    ↓
await GLMEnhancer.enhance(card) → Mock增强(三锁关) / Real增强(三锁开+fake adapter)
    ↓
CandidatePool.route_card(card) → 三池分流(pending_review/observing/discarded)
    ↓
DualReviewGate.check(card) → 高风险双审核
    ↓
CostTracker.record_cost()
    ↓
RouteResult (结构化输出)
```

## 路由场景

| task_type | Primary | Fallback | F3 Emergency |
|-----------|---------|----------|--------------|
| chinese_industry_news | Bocha | GLM | codeact(标记) |
| global_ai_tools | Tavily | GLM | codeact(标记) |
| official_docs | Tavily | Bocha | codeact(标记) |
| technical_research | Tavily | GLM | codeact(标记) |
| fallback_light_search | GLM(free) | — | codeact(标记) |

dry_run 阶段全部走 Mock。codeact 仅 F3 标记，不真实调用。

## CLI 使用说明

### 单次搜索

```bash
cd ZHIPU_WUGE_SEARCH_ROUTER_P0_T5_ENTRY_LAYER_20260627/p0_t5
python examples/run_single_search.py --query "美业 AI 趋势" --task-type chinese_industry_news --max-results 5
```

输出 JSON 到 stdout，包含 cards / pool_decisions / review_decisions / total_cost / metadata。

### 每日情报

```bash
python examples/run_daily_intel.py --date 20260627 --dimensions "数字化与AI工具,品牌与产品"
```

按维度批量搜索，输出 JSON。

## 测试

```bash
cd ZHIPU_WUGE_SEARCH_ROUTER_P0_T5_ENTRY_LAYER_20260627/p0_t5
python -m pytest tests/ -q
```

| 分组 | 用例数 | 通过 |
|------|--------|------|
| T1 回归 | 82 | 82 ✅ |
| T2A 回归 | 72 | 72 ✅ |
| T2B 回归 | 103 | 103 ✅ |
| T3 回归 | 155 | 155 ✅ |
| T4 回归 | 79 | 79 ✅ |
| T5 新增 | 35 | 35 ✅ |
| **合计** | **526** | **526** ✅ |

## 安全

详见 `SECURITY_NOTE.md`，测试详情见 `TEST_REPORT.md`。
