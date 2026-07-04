# M1-W0.5 模型路由与兜底层候选代码独立复核报告

- **版本**: V1
- **复核日期**: 2026-07-04
- **复核人**: Qoder（独立复核角色）
- **复核分支**: `qoder/m1-w0_5-model-router-review`（基于 `claude/model-routing-fallback-layer-qcpa3w`）
- **目标 commit**: `6ba819d`
- **代码状态**: CODE_CANDIDATE（不得合并 main / 不得部署 / 不得启动 M1）

---

## 一、分支与 Commit

| 项目 | 值 |
|---|---|
| 源分支 | `claude/model-routing-fallback-layer-qcpa3w` |
| commit | `6ba819d feat(model-router): 模型路由与兜底层 V0.1 落码（M1条件施工·mock阶段）` |
| 父 commit | `d0fbdff merge: review/content-bot-switch-claude → main` |
| 复核分支 | `qoder/m1-w0_5-model-router-review` |
| main 是否包含此 commit | **否**（main 停在 d0fbdff） |
| origin/main 是否包含此 commit | **否** |

---

## 二、Changed Files

全部 11 个文件均为**新增（A）**，无任何已有文件被修改：

```
A  backend/app/model_router/__init__.py
A  backend/app/model_router/call_log.py
A  backend/app/model_router/circuit_breaker.py
A  backend/app/model_router/clients.py
A  backend/app/model_router/config.py
A  backend/app/model_router/prescan.py
A  backend/app/model_router/router.py
A  backend/app/model_router/schemas.py
A  backend/app/model_router/sensitive_guard.py
A  docs/M1/MODEL_ROUTER_AND_FALLBACK_DESIGN_V0_1.md
A  tests/test_model_router.py
```

---

## 三、Git Diff --stat

```
 backend/app/model_router/__init__.py             |  45 +++
 backend/app/model_router/call_log.py             | 114 +++++++
 backend/app/model_router/circuit_breaker.py      | 120 +++++++
 backend/app/model_router/clients.py              |  67 ++++
 backend/app/model_router/config.py               |  78 +++++
 backend/app/model_router/prescan.py              |  38 +++
 backend/app/model_router/router.py               | 341 ++++++++++++++++++++
 backend/app/model_router/schemas.py              | 130 ++++++++
 backend/app/model_router/sensitive_guard.py      |  60 ++++
 docs/M1/MODEL_ROUTER_AND_FALLBACK_DESIGN_V0_1.md | 337 ++++++++++++++++++++
 tests/test_model_router.py                       | 381 +++++++++++++++++++++++
 11 files changed, 1711 insertions(+)
```

---

## 四、Pytest 原始输出

```
platform win32 -- Python 3.14.5, pytest-9.1.0, pluggy-1.6.0
collected 45 items

tests/test_model_router.py::TestHappyPath::test_fact_strict_routes_to_primary PASSED
tests/test_model_router.py::TestHappyPath::test_platform_rewrite_routes_to_rewrite PASSED
tests/test_model_router.py::TestHappyPath::test_output_binds_used_materials_ids PASSED
tests/test_model_router.py::TestHappyPath::test_publish_allowed_is_constant_false PASSED
tests/test_model_router.py::TestHappyPath::test_state_aesthetic_gets_rewrite_polish PASSED
tests/test_model_router.py::TestHappyPath::test_high_risk_double_check_and_must_sign PASSED
tests/test_model_router.py::TestHappyPath::test_restricted_expansion_prompt_for_kimi_candidates PASSED
tests/test_model_router.py::TestMissingMaterials::test_empty_materials_yields_report_not_candidate PASSED
tests/test_model_router.py::TestMissingMaterials::test_no_model_called_when_materials_empty PASSED
tests/test_model_router.py::TestFallback::test_primary_timeout_switches_to_fallback PASSED
tests/test_model_router.py::TestFallback::test_quality_fail_retries_then_fallback PASSED
tests/test_model_router.py::TestFallback::test_banned_word_no_retry_same_model PASSED
tests/test_model_router.py::TestFallback::test_double_failure_trips_stop_manual_review PASSED
tests/test_model_router.py::TestFallback::test_fallback_output_passes_same_gates PASSED
tests/test_model_router.py::TestSensitiveGuard::test_scan_detects_credentials_privacy_raw_business PASSED
tests/test_model_router.py::TestSensitiveGuard::test_low_cost_model_blocked_on_sensitive_data PASSED
tests/test_model_router.py::TestSensitiveGuard::test_primary_not_low_cost_allows_task PASSED
tests/test_model_router.py::TestCircuitBreaker::test_primary_streak_trips_hold PASSED
tests/test_model_router.py::TestCircuitBreaker::test_open_breaker_queues_tasks_not_drops PASSED
tests/test_model_router.py::TestCircuitBreaker::test_no_auto_recovery_release_requires_operator PASSED
tests/test_model_router.py::TestCircuitBreaker::test_g1_fail_streak_same_content_trips_stop PASSED
tests/test_model_router.py::TestCircuitBreaker::test_max_calls_per_content_trips_stop PASSED
tests/test_model_router.py::TestCircuitBreaker::test_daily_cost_over_limit_trips_stop PASSED
tests/test_model_router.py::TestCallLog::test_all_required_fields_present PASSED
tests/test_model_router.py::TestCallLog::test_free_model_zero_cost_but_recorded PASSED
tests/test_model_router.py::TestCallLog::test_cost_computed_from_tokens PASSED
tests/test_model_router.py::TestCallLog::test_every_call_logged_including_failures PASSED
tests/test_model_router.py::TestPrescan::test_banned_samples_hit (11 parametrized) PASSED
tests/test_model_router.py::TestPrescan::test_allowed_samples_pass (5 parametrized) PASSED
tests/test_model_router.py::TestConfig::test_default_has_four_roles_provider_tbd PASSED
tests/test_model_router.py::TestConfig::test_from_dict_matches_design_json PASSED

============================= 45 passed in 0.12s ==============================
```

---

## 五、Grep 红线结果

在 `backend/app/model_router/` 全目录 + `tests/test_model_router.py` 中执行以下关键词搜索：

| 关键词 | 命中数 | 判定 |
|---|---|---|
| `/content/generate` | 0 | PASS |
| `publish_allowed`（作为可写赋值） | 仅 `field(default=False, init=False)` 常量声明 | PASS |
| `writes_approved`（作为可写赋值） | 仅 `field(default=False, init=False)` 常量声明 | PASS |
| `approved`（作为写入操作） | 0（仅在设计文档中作为"不得写入"的引用） | PASS |
| `reindex` | 0 | PASS |
| `9200` | 0 | PASS |
| `site_published` | 0 | PASS |
| `requests` / `httpx` / `urllib` / `aiohttp` | 0 | PASS |
| `FastAPI` / `include_router` / `APIRouter` | 0 | PASS |

---

## 六、20 条严禁逐条核查

| # | 严禁项 | 核查结果 | 证据 |
|---|---|---|---|
| 1 | 不得合并 main | PASS | main 停在 d0fbdff，不含 6ba819d |
| 2 | 不得部署 | PASS | 无任何部署脚本/CI/CD 触发 |
| 3 | 不得启动 M1 | PASS | 无 M1 启动代码 |
| 4 | 不得接 /content/generate | PASS | grep 零命中 |
| 5 | 不得接真实发布池 | PASS | 无发布相关代码 |
| 6 | 不发起真实模型调用 | PASS | 仅 MockModelClient，无 HTTP 库引用 |
| 7 | 不挂载 FastAPI 路由 | PASS | 无 FastAPI/APIRouter/include_router |
| 8 | 不写 approved | PASS | `writes_approved = field(default=False, init=False)` 常量 |
| 9 | 不自动发布 | PASS | `publish_allowed = field(default=False, init=False)` 常量 |
| 10 | 不接 9200 | PASS | grep 零命中 |
| 11 | 不 reindex | PASS | grep 零命中 |
| 12 | 不传密钥给免费模型 | PASS | `sensitive_guard.scan_sensitive` 拦截 + `router._draft_with_fallback` 调用前检查 |
| 13 | 不传隐私给免费模型 | PASS | 手机号/证件号/客户信息正则+关键词双重拦截 |
| 14 | 不传未脱敏门店数据给免费模型 | PASS | `_RAW_BUSINESS_KEYWORDS` 关键词拦截 |
| 15 | 缺料不出候选稿 | PASS | `generate_draft` 首行检查 `if not task.used_materials` → 返回 `MissingMaterialReport` |
| 16 | fallback 输出过同一套门 | PASS | `_run_gates` 对 primary 和 fallback 输出执行相同扫描 |
| 17 | 不自动恢复熔断 | PASS | `release` 必须传 operator+note，否则 ValueError |
| 18 | 不丢弃排队任务 | PASS | `queued_tasks` 列表保留，release 时返回 |
| 19 | 不限重试同失败模型 | PASS | `failed_models` 集合 + 不重复调用 |
| 20 | 不禁 G1 命中打回不重试 | PASS | 禁用词命中 → `break`，不 retry 同模型 |

---

## 七、8 条数据模型边界逐条核查

| # | 边界 | 核查结果 | 证据 |
|---|---|---|---|
| 1 | TaskStatus 无 approved/published 枚举值 | PASS | 仅 `draft_candidate/missing_materials/failed/manual_review/held/blocked_sensitive` |
| 2 | RouterResult.publish_allowed 为常量 False | PASS | `field(default=False, init=False)` 无写入口，测试验证 TypeError |
| 3 | RouterResult.writes_approved 为常量 False | PASS | 同上 |
| 4 | MissingMaterialReport.enters_gates 恒 False | PASS | `field(default=False)` |
| 5 | MissingMaterialReport.enters_candidate_review 恒 False | PASS | `field(default=False)` |
| 6 | DraftTask.used_materials 为空时不触发模型调用 | PASS | 测试 `test_no_model_called_when_materials_empty` 断言 `all(len(c.calls) == 0)` |
| 7 | RouterResult.used_materials_ids 必须绑定 | PASS | `router.py:170` 赋值 `task.used_materials_ids`，测试验证 |
| 8 | CallLogEntry 包含 14 个必记字段 | PASS | `REQUIRED_FIELDS` 列表 + 测试 `test_all_required_fields_present` |

---

## 八、敏感信息拦截测试结果

| 测试场景 | 结果 | 证据 |
|---|---|---|
| API Key 特征（`api_key: sk-xxx`） | 拦截 | `test_scan_detects_credentials_privacy_raw_business` PASS |
| 手机号（`13812345678`） | 拦截 | 同上，含紧贴中文场景 `给王女士13812345678写回访` |
| 身份证号（18 位） | 拦截 | `_PRIVACY_PATTERNS` 正则覆盖 |
| 真实经营数据关键词 | 拦截 | `_RAW_BUSINESS_KEYWORDS` 覆盖 |
| 已脱敏数据（`store_001`） | 不拦截 | 测试断言 `scan_sensitive(...) == []` |
| 低成本模型收到敏感任务 | 拒发 | `test_low_cost_model_blocked_on_sensitive_data` PASS，状态 `BLOCKED_SENSITIVE` |
| 主模型（非低成本）不触发拦截 | 正常通过 | `test_primary_not_low_cost_allows_task` PASS |

---

## 九、Fallback 纪律测试结果

| 测试场景 | 结果 | 证据 |
|---|---|---|
| 主模型超时 → 自动切 fallback | PASS | `test_primary_timeout_switches_to_fallback` |
| 质量不达标 → 同模型重试 ≤2 次 → 切 fallback | PASS | `test_quality_fail_retries_then_fallback`，primary 调用 3 次 |
| G1 禁用词命中 → 不重试同模型 → 切 fallback | PASS | `test_banned_word_no_retry_same_model`，primary 仅 1 次调用 |
| 主+fallback 双失败 → stop + manual_review | PASS | `test_double_failure_trips_stop_manual_review` |
| fallback 输出过同一套 gate pipeline | PASS | `test_fallback_output_passes_same_gates` |
| 不重复调用同一失败模型 | PASS | `failed_models` 集合去重逻辑 |

---

## 十、used_materials 缺料报告测试结果

| 测试场景 | 结果 | 证据 |
|---|---|---|
| 空素材 → 返回 MissingMaterialReport | PASS | `test_empty_materials_yields_report_not_candidate` |
| 缺料报告 status = MISSING_MATERIALS | PASS | 断言 `res.status == TaskStatus.MISSING_MATERIALS` |
| 缺料报告不进六硬门 | PASS | `res.enters_gates is False` |
| 缺料报告不进候选审读 | PASS | `res.enters_candidate_review is False` |
| 缺料报告包含缺失类型和建议关键词 | PASS | `res.missing_material_types and res.suggested_recall_keywords` |
| 空素材时模型零调用 | PASS | `test_no_model_called_when_materials_empty` |

---

## 十一、是否存在真实网络调用

**否。**

- `backend/app/model_router/` 全目录无 `requests` / `httpx` / `urllib` / `aiohttp` 引用
- 模型客户端仅有 `MockModelClient`（内存实现，返回预置脚本）
- `ModelClient` 为 Protocol 接口定义，无实际网络实现
- config.py 密钥注释明确："真实接入时经环境变量注入，本层 mock 阶段无密钥"

---

## 十二、是否存在 FastAPI 路由挂载

**否。**

- 无 `FastAPI` / `APIRouter` / `include_router` 引用
- `__init__.py` 模块注释明确："不挂载任何 FastAPI 路由（不开 /content/generate）"
- 本包为纯库层代码，无任何 HTTP 端点

---

## 十三、是否存在 /content/generate

**否。** grep 零命中。

---

## 十四、是否存在 approved / reindex / 9200

| 关键词 | 源码目录 | 测试文件 | 设计文档 |
|---|---|---|---|
| `approved` | 仅作为常量 `writes_approved=False` + 注释引用"不写 approved" | 仅作为断言 `writes_approved is False` | 设计说明中引用 |
| `reindex` | 0 | 0 | 设计文档 7.3 "不 reindex" |
| `9200` | 0 | 0 | 设计文档 7.1 "不直连 9200" |

**结论：无写入操作、无网络访问、无库操作。全部 PASS。**

---

## 十五、回滚验证

| 步骤 | 结果 |
|---|---|
| `git revert --no-commit 6ba819d` | 执行成功，无冲突 |
| diff --cached --stat | 11 files changed, 1711 deletions(-)，与新增完全对称 |
| `backend/app/model_router/` 目录文件 | 全部清空，无残留文件 |
| `docs/M1/` 设计文档 | 已移除 |
| `tests/test_model_router.py` | 已移除 |
| `git reset --hard HEAD` 恢复 | 成功恢复至 6ba819d |

**结论：`git revert 6ba819d` 可完整回滚，无库侧残留。**

---

## 十六、Qoder 是否修补

**否。** 本次复核未发现需要修补的问题。

---

## 十七、修补文件清单

无。

---

## 十八、风险项

| # | 风险 | 等级 | 说明 |
|---|---|---|---|
| 1 | G1 预扫描词表为硬编码子集 | 低 | 文档已明确说明"本词表为预扫描子集，不得反向缩小正式门的覆盖范围"；W4 工单实现完整 G1-G6 后规则外置配置文件 |
| 2 | `prescan_g1` 在 `_run_gates` 中被调用两次 | 低 | `router.py:274` 中 `prescan_g1(text)` 被调用一次取值、再调用一次取 hits，可优化为单次调用。但当前不影响正确性，属于性能微优化 |
| 3 | CallLog 为内存实现 | 低 | 文档已标注"M1 mock 阶段为内存实现；持久化属 W6 工单" |
| 4 | quality_score 由 mock 脚本注入 | 低 | 文档已标注"mock 阶段由脚本注入；真实阶段由 review_model 评出" |

以上均为已标注的 mock 阶段限制，非红线问题，不需要当前修补。

---

## 十九、结论

### **PASS**

**结论说明：**

1. 11 个文件全部新增，零修改已有代码；
2. 45/45 测试全部通过；
3. 全量 grep 红线核查零违规；
4. 20 条严禁逐条通过；
5. 8 条数据模型边界逐条通过；
6. 敏感信息拦截测试真实通过（含手机号紧贴中文场景）；
7. Fallback 纪律测试真实通过；
8. 缺料报告测试真实通过；
9. 无真实网络调用、无 FastAPI 路由、无 /content/generate；
10. 无 approved/reindex/9200 写入或访问；
11. `git revert 6ba819d` 可完整回滚；
12. 测试代码非伪造——每个测试有明确断言逻辑、正反样例覆盖；
13. Qoder 未做修补——无需修补。

**本结论只代表 W0.5 模型层基础件通过，不代表 M1 启动。**

---

## 二十、下一步纪律

1. 本报告交付吴哥和 ChatGPT 复核；
2. ChatGPT 复核通过后，再决定是否允许进入 W1/W2；
3. **不允许直接进入 W4**；
4. 代码链交给 Qoder（本报告），部署链交给扣子；
5. Claude 可以写，Qoder 必须审，扣子只部署，吴哥最后拍板。
