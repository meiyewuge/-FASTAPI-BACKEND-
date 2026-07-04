# M1_W1_W2_QODER_PATCH_REPORT_V1

## Claude Code V2 反审修补报告

| 项目 | 内容 |
|---|---|
| 修补工单 | M1-W1/W2 Patch A/B/C + TODO D |
| 修补分支 | `qoder/m1-w1-w2-factory-skeleton-recall` |
| 修补 commit | `4f6670f` |
| 修补依据 | Claude Code V2 反向审查报告 |
| 修补日期 | 2026-07-04 |

---

## 1. 新 Commit Hash

```
4f6670f fix(content-factory): Patch A/B/C — 缺料停单+ Brief边界字段+ fail-closed过滤器 (Claude Code V2 反审修补)
```

## 2. Changed Files

8 个文件修改（6 源码 + 2 测试）：

| 文件 | 修补项 |
|---|---|
| `backend/app/content_factory/schemas.py` | A: HALTED_MISSING_MATERIALS 态; B: target_platform/line/direction_hint 字段; FactoryResult.missing_report |
| `backend/app/content_factory/task_state.py` | A: producing→halted 转换 + 终态判定 |
| `backend/app/content_factory/factory.py` | A: bind_materials 接入 + 缺料停单; C: apply_filters 接入; D: TODO |
| `backend/app/content_factory/brief.py` | B: target_platform 必填四选一 + line 锁死 + direction_hint + InvalidPlatformError |
| `backend/app/content_factory/recall/filters.py` | C: fail-closed + M1 黑名单 |
| `backend/app/content_factory/__init__.py` | B: 导出 InvalidPlatformError |
| `tests/test_factory_brief.py` | A: 4 项缺料停单测试; B: 7 项边界字段测试; 全量更新已有测试 |
| `tests/test_factory_recall.py` | C: 3 项 fail-closed + 7 项 M1 黑名单测试; 全量更新已有测试 |

## 3. Git Diff --stat

```
 backend/app/content_factory/__init__.py       |   3 +-
 backend/app/content_factory/brief.py          |  40 +++++-
 backend/app/content_factory/factory.py        |  56 ++++++--
 backend/app/content_factory/recall/filters.py |  50 +++++--
 backend/app/content_factory/schemas.py        |  30 ++++-
 backend/app/content_factory/task_state.py     |  22 +++-
 tests/test_factory_brief.py                   | 181 +++++++++++++++++++++++---
 tests/test_factory_recall.py                  | 161 +++++++++++++++++++----
 8 files changed, 463 insertions(+), 80 deletions(-)
```

## 4. Pytest 原始输出

```
============================= test session starts =============================
platform win32 -- Python 3.14.5, pytest-9.1.0, pluggy-1.6.0
rootdir: C:\Users\thinkpad\Downloads\-FASTAPI-BACKEND-
collected 154 items
============================= 154 passed in 0.21s =============================
```

新增 21 项测试（原 133 → 154）。

## 5. 修补 A：缺料停单链路

### 代码位置

| 文件 | 修改内容 |
|---|---|
| `schemas.py` | 新增 `FactoryTaskState.HALTED_MISSING_MATERIALS` 终态 |
| `task_state.py` | `PRODUCING → HALTED_MISSING_MATERIALS` 合法转换 + `is_terminal` 包含 halted |
| `factory.py:process_brief` | Step 2.5: 召回后调用 `bind_materials`，`is_sufficient=False` 时停单 |
| `factory.py:FactoryResult` | 新增 `missing_report` 字段 |

### 修补逻辑

```
process_brief → recall → apply_filters → bind_materials
  → is_sufficient=False → HALTED_MISSING_MATERIALS (终态, 不进 PACKAGED, 不进 staging 候选)
  → is_sufficient=True → GATED → PACKAGED → staging
```

### 测试

| 测试 | 验证 |
|---|---|
| `test_zero_materials_halted` | 零素材 → HALTED_MISSING_MATERIALS |
| `test_halted_not_in_staging_candidate` | 缺料停单后不进 PACKAGED staging |
| `test_blocked_recall_halted` | 召回被拦截 → 停单 |
| `test_halted_is_terminal` | halted 是终态 |

## 6. 修补 B：Brief 边界字段

### 代码位置

| 文件 | 修改内容 |
|---|---|
| `schemas.py:Brief` | 新增 `target_platform`（必填）、`line`（默认 brand_dfd）、`direction_hint`（可选） |
| `schemas.py` | 新增 `VALID_TARGET_PLATFORMS` 集合 + `M1_LOCKED_LINE` 常量 |
| `brief.py:parse_brief` | target_platform 四选一必填 + line 锁死验证 + direction_hint 解析 |
| `brief.py` | 新增 `InvalidPlatformError` 异常类 |

### 测试

| 测试 | 验证 |
|---|---|
| `test_missing_platform_fails` | 缺 platform → BriefParseError |
| `test_invalid_platform_fails` | 非法 platform → InvalidPlatformError |
| `test_valid_platforms_accepted` | 4 个合法平台全部接受 |
| `test_line_non_brand_dfd_rejected` | 非 brand_dfd → 拒绝 |
| `test_line_default_brand_dfd` | 默认 brand_dfd |
| `test_direction_hint_stored` | direction_hint 正确存储 |
| `test_direction_hint_not_in_used_materials` | direction_hint 不进 used_materials |

## 7. 修补 C：过滤器 fail-closed + M1 黑名单

### 代码位置

| 文件 | 修改内容 |
|---|---|
| `filters.py:apply_filters` | fail-closed: material_type/source_type/status 缺失 → 拒绝 |
| `filters.py:DEFAULT_BLACKLIST` | 新增 10 项 M1 黑名单条目 |
| `factory.py:process_brief` | 召回后自动 apply_filters |

### M1 黑名单新增条目

`raw_draft`, `kimi_expansion`, `daily_brief`, `daily_report`, `webintel`, `webintel_crawl`, `crawl_raw`, `crawl_unverified`, `craft_memory`, `platform_inspiration_as_fact`

### 测试

| 测试 | 验证 |
|---|---|
| `test_missing_material_type_rejected` | 缺 material_type → 拒绝 |
| `test_missing_source_type_rejected` | 缺 source_type → 拒绝 |
| `test_missing_status_rejected` | 缺 status → 拒绝 |
| `test_kimi_expansion_blocked` | Kimi 扩写件 → 过滤 |
| `test_daily_brief_blocked` | DAILY_* → 过滤 |
| `test_webintel_blocked` | WEBINTEL_* → 过滤 |
| `test_crawl_blocked` | crawl_* → 过滤 |
| `test_craft_memory_blocked` | craft_memory → 过滤 |
| `test_platform_inspiration_as_fact_blocked` | 平台灵感当事实 → 过滤 |
| `test_raw_draft_blocked` | raw_draft → 过滤 |

## 8. 红线 Grep

| 关键词 | content_factory/ 命中数 |
|---|---|
| `/content/generate` | 0 |
| `9200` | 0 |
| `reindex` | 0 |
| `httpx` / `requests.get/post` | 0 |
| `FastAPI` / `include_router` | 0 |
| `approved = True` / `writes_approved` | 0 |
| `candidate_pool` | 0 |

## 9. 是否触达 /content/generate

**否。** 未挂载任何 FastAPI 路由。

## 10. 是否触达 9200

**否。** 纯 mock 实现，不发起任何网络调用。

## 11. 是否新增 HTTP 库

**否。** 未引入 httpx / requests / aiohttp 等。

## 12. 是否挂 FastAPI

**否。** 未 import FastAPI / APIRouter / include_router。

## 13. 是否写 approved/reindex/candidate_pool

**否。** grep 全部零命中。

## 14. 回滚说明

```
git revert --no-commit 4f6670f
→ 8 files changed, 80 insertions(+), 463 deletions(-)
→ 完整回滚，无冲突
```

## 15. 结论

### **PASS**

**修补摘要：**

- A: 缺料停单链路 — `bind_materials` 接入 `process_brief`，零素材 → HALTED_MISSING_MATERIALS 终态，不进 PACKAGED，不进 staging 候选
- B: Brief 边界字段 — `target_platform` 必填四选一、`line` 锁死 brand_dfd、`direction_hint` 不进 used_materials
- C: 过滤器 fail-closed — material_type/source_type/status 缺失 → 拒绝；M1 黑名单补入 10 项
- D: TODO 标记 — RecallLog 接入(W6) + source_refs 句级溯源(W3)

**核心数据：**

- 8 文件修改，463 行新增，80 行删除
- 154/154 测试全部通过（新增 21 项）
- grep 红线：全部零命中
- `git revert 4f6670f` 完整回滚
- 已推送到远端 `qoder/m1-w1-w2-factory-skeleton-recall`

**本结论只代表 W1/W2 修补通过，不代表 M1 启动。**

---

## 下一步纪律

1. 报告交付 Claude Code 做增量复验 V3
2. Claude Code V3 通过后交 ChatGPT 终审
3. ChatGPT 终审通过后交吴哥拍板
4. 不进入 W3 / W4 / 不合并 main / 不部署 / 不启动 M1
