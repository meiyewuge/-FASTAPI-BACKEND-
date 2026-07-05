# M1-W8 Qoder 联调沙盒骨架施工报告 V1

---

## 1. 分支与 Commit

| 项目 | 值 |
|---|---|
| 分支 | `qoder/m1-w8-sandbox-integration-skeleton` |
| 基准 commit | `eeecae2` (W7 PASS, 307 tests) |
| HEAD | `d6d84cb` |
| 是否推 main | **否** |

---

## 2. G0 远端对账

| 项目 | 结果 |
|---|---|
| fetch origin | PASS |
| 基线分支 | `qoder/m1-w8-sandbox-integration-skeleton`（从 `eeecae2` 新建） |
| 基线 pytest | 307 passed, 0 failed |
| W8 后 pytest | **349 passed, 0 failed**（+42 W8 测试） |
| 回归 | **零** |

---

## 3. Changed Files

| 文件 | 类型 | 行数 |
|---|---|---|
| `backend/app/content_factory/sandbox/__init__.py` | 新增 | 28 |
| `backend/app/content_factory/sandbox/contracts.py` | 新增 | 284 |
| `backend/app/content_factory/sandbox/fixtures.py` | 新增 | 170 |
| `backend/app/content_factory/sandbox/runner.py` | 新增 | 167 |
| `backend/app/content_factory/sandbox/schemas.py` | 新增 | 67 |
| `tests/test_w8_sandbox_integration.py` | 新增 | 507 |
| **合计** | 6 files | **1223 insertions** |

---

## 4. Git Diff --stat

```
 backend/app/content_factory/sandbox/__init__.py  |  28 ++
 backend/app/content_factory/sandbox/contracts.py | 284 +++++++++++++
 backend/app/content_factory/sandbox/fixtures.py  | 170 ++++++++
 backend/app/content_factory/sandbox/runner.py    | 167 ++++++++
 backend/app/content_factory/sandbox/schemas.py   |  67 +++
 tests/test_w8_sandbox_integration.py             | 507 +++++++++++++++++++++++
 6 files changed, 1223 insertions(+)
```

---

## 5. W8 实现范围

### 5.1 sandbox 子包（5 文件）

| 模块 | 职责 |
|---|---|
| `__init__.py` | 子包入口，统一导出 |
| `schemas.py` | `SandboxPathKind`（6 路径枚举）+ `SandboxResult`（出口约束恒 False） |
| `runner.py` | `SandboxRunner` 主编排器：Brief → factory → midplatform → observer → SandboxResult |
| `fixtures.py` | 全链路 mock fixture 构造器：素材/路由器/门检/中台/观测/日报 |
| `contracts.py` | rulepack / feature_flags / readiness / W1-W7 兼容性契约校验 |

### 5.2 测试文件（1 文件，42 项测试）

| 测试类 | 覆盖路径 | 测试数 |
|---|---|---|
| `TestSuccessPath` | SUCCESS（PACKAGED） | 7 |
| `TestMissingMaterialsPath` | MISSING_MATERIALS | 4 |
| `TestBlockedDraftPath` | BLOCKED_DRAFT（W3 拦截） | 3 |
| `TestGateBlockedPath` | GATE_BLOCKED（W4 拦截） | 2 |
| `TestHumanReviewPath` | HUMAN_REVIEW（conditional_pass） | 4 |
| `TestDailyReportPath` | DAILY_REPORT（日报） | 4 |
| `TestContractValidations` | 契约校验 | 5 |
| `TestSandboxResultConstraints` | 出口约束 | 4 |
| `TestRunnerSummary` | Runner 汇总 | 2 |
| `TestQoderStrengthening` | Qoder 补强 | 7 |
| **合计** | | **42** |

### 5.3 实现边界

- **已实现**：全 mock 联调链路（Brief → W1/W2 召回 → W3 草稿 → W4 六硬门 → W5 审读包 → W6 日报 → W7 契约 → sandbox result）
- **未实现**：真实服务接入（严禁项）

---

## 6. Sandbox Runner 说明

### 6.1 编排链路

```
Brief dict
  → parse_brief → Brief 对象
  → ContentFactory.process_brief（recall → bind → DraftGenerator → GatePipeline）
  → MidPlatformMock.ingest_factory_result（队列 / 前台提示）
  → ProductionLineObserver.observe（观测记录）
  → SandboxResult（路径分类 + 出口约束）
```

### 6.2 六条沙盒路径

| 路径 | 触发条件 | factory_state |
|---|---|---|
| SUCCESS | 充足素材 + 清洁稿 + 门检通过 | PACKAGED |
| MISSING_MATERIALS | recall_client=None 或素材不足 | HALTED_MISSING_MATERIALS |
| BLOCKED_DRAFT | W3 无源事实句/新增事实拦截 | BLOCKED_DRAFT |
| GATE_BLOCKED | W4 六硬门全 fail | GATE_BLOCKED |
| HUMAN_REVIEW | G1 conditional_pass（谨慎词） | PACKAGED + needs_human_review |
| DAILY_REPORT | build_daily_report 聚合 | — |

### 6.3 GATE_BLOCKED 路径架构说明

`ModelRouter._draft_with_fallback` 自带 `prescan_g1` 预扫描，命中 G1 禁用词后在路由器层即拦截（`MANUAL_REVIEW`），文本无法到达 `GatePipeline`（W4）。这是**正确的防御纵深设计**。

因此 GATE_BLOCKED 路径测试采用**手工构造 OK 版本 + 直接跑 GatePipeline** 的方式，单独验证 W4 门检层的 G1-G6 拦截能力，不经过路由器预扫描。

---

## 7. W1-W7 接口兼容性检查

`validate_w1_w7_compat()` 逐项验证 W1-W8 各子包可导入、可实例化：

| 子包 | 检查项 | 结果 |
|---|---|---|
| W1 brief | `parse_brief()` 可调用 | PASS |
| W2 recall | `MockRecallClient` 可实例化 | PASS |
| W3 drafting | `DraftGenerator` 可实例化 | PASS |
| W4 gates | `GatePipeline` 可实例化 | PASS |
| W5 midplatform | `MidPlatformMock` 可实例化 | PASS |
| W6 observability | `ProductionLineObserver` 可实例化 | PASS |
| W7 rules | `RulePackStore` 可实例化 | PASS |
| W8 sandbox | `SandboxRunner` 可实例化 | PASS |

---

## 8. Rulepack / Feature Flags / Readiness 校验

### 8.1 Rulepack 校验

| 检查项 | 结果 |
|---|---|
| 六门规则齐备（G1-G6） | PASS |
| MD5 可校验 | PASS |
| `is_mock=True` | PASS |
| `is_production_ready=False` | PASS |
| 四平台规则集（xiaohongshu/douyin/shipinhao/brand_site） | PASS |

### 8.2 Feature Flags 校验

| 检查项 | 结果 |
|---|---|
| 7 个 flag 默认 False | PASS |
| `any_enabled()=False` | PASS |
| `as_dict()` 全 False | PASS |

### 8.3 Readiness Checklist 校验

| 检查项 | 结果 |
|---|---|
| `is_ready=False` | PASS |
| 全部 `done=False` | PASS |
| 5 张清单齐备 | PASS |

---

## 9. SandboxResult 数据结构

```python
@dataclass
class SandboxResult:
    path: SandboxPathKind           # 六路径枚举
    factory_state: FactoryTaskState # 工厂终态
    content_id: str
    brief_id: str
    trace_id: str
    text: Optional[str] = None
    recall_summary: Dict[str, Any]
    used_materials_ids: List[str]
    gate_review_status: Optional[str]
    review_queue_state: Optional[str]
    daily_report: Optional[Dict[str, Any]]
    # ── 常量出口约束（init=False，无写入口）──
    publish_allowed: bool = False       # 恒 False
    writes_approved: bool = False       # 恒 False

    @property
    def is_sandbox_pass(self) -> bool:  # 链路跑通 ≠ 可上线
    @property
    def is_production_signal(self) -> bool:  # 恒 False
```

---

## 10. Pytest 原始输出

```
============================= test session starts =============================
platform win32 -- Python 3.14.5, pytest-9.1.0, pluggy-1.6.0
rootdir: C:\Users\thinkpad\Downloads\-FASTAPI-BACKEND-
plugins: anyio-4.13.0
collected 349 items

tests\test_factory_brief.py .......................................      [ 11%]
tests\test_factory_recall.py .............................               [ 19%]
tests\test_guardrails.py ............................................... [ 32%]
tests\test_model_router.py ............................................. [ 45%]
tests\test_w3_draft_generation.py ...................................    [ 55%]
tests\test_w4_gate_pipeline.py ........................................  [ 67%]
tests\test_w5_review_package_midplatform.py ......................       [ 73%]
tests\test_w6_daily_observability.py ....................                [ 79%]
tests\test_w7_rules_observability_readiness.py ......................... [ 86%]
.....                                                                    [ 87%]
tests\test_w8_sandbox_integration.py ................................... [ 97%]
.......                                                                  [100%]

============================= 349 passed in 0.41s =============================
```

---

## 11. 红线 Grep

对 sandbox 子包（5 文件）+ 测试文件（1 文件）执行严禁项 grep：

| 关键词 | 命中 | 分析 | 违规 |
|---|---|---|---|
| `approved` | 3 | docstring 严禁声明 + mock 素材 `"source_type": "9080_approved"` marker | **零违规** |
| `site_published` | 0 | — | **零** |
| `/content/generate` | 0 | — | **零** |
| `9080` | 3 | docstring 严禁声明 + mock 素材 marker | **零违规** |
| `9200` | 2 | docstring 严禁声明 | **零违规** |
| `reindex` | 1 | docstring 严禁声明 | **零违规** |

**结论：红线 grep 零违规。**

---

## 12. 是否触达真实发布

**否。** 全链路为 mock：
- `publish_allowed` 恒 False（`init=False`，无写入口）
- `writes_approved` 恒 False
- `is_production_signal` 恒 False
- 无 `site_published` 产出

---

## 13. 是否写 approved

**否。** sandbox 代码中无任何 `approved` 写入操作。唯一出现的 `"9080_approved"` 为 mock 素材的 `source_type` 标记常量。

---

## 14. 是否触达 /content/generate

**否。** sandbox 子包及测试文件中零命中 `/content/generate`。

---

## 15. 是否触达真实 9080

**否。** `MockRecallClient` 配置 `base_url="mock"`, `mock=True`。所有召回均为预置内存素材。

---

## 16. 是否接真实模型

**否。** `MockModelClient` 配置 `provider="mock"`, `model_name="mock-sandbox"`。4 角色（primary/review/rewrite/fallback）全为 mock。

---

## 17. 是否接真实数据库/监控/定时任务

**否。**

| 组件 | 实现 | 真实接入 |
|---|---|---|
| 数据库 | 无 | 全部内存 dataclass |
| 监控 | `ProductionLineObserver`（内存） | 无 |
| 定时任务 | `MockScheduler`（内存） | 无 |
| 日报存储 | `MockReportStore`（内存） | 无 |
| 告警 | `MockAlertSink`（内存） | 无 |

---

## 18. 回滚说明

W8 sandbox 子包为**纯新增文件**，不修改任何 W1-W7 已有代码。回滚操作：

```bash
# 删除 sandbox 子包
git rm -r backend/app/content_factory/sandbox/
# 删除测试文件
git rm tests/test_w8_sandbox_integration.py
# 或整体回退
git revert <commit-hash>
```

回滚后 W1-W7 全部 307 项测试不受影响。

---

## 19. 风险项

| 风险 | 等级 | 说明 |
|---|---|---|
| GATE_BLOCKED 路径需手工构造 | 低 | 路由器 prescan 先于门检拦截是正确设计；手工构造 OK 版本可独立验证 W4 门检层 |
| mock 素材 marker `"9080_approved"` | 低 | 仅为测试数据标记，非真实 9080 调用 |
| sandbox pass 误解为生产可用 | 已消除 | `is_production_signal` 恒 False + 文档明确标注 |

---

## 20. 结论

### **PASS**

| 验收项 | 结果 |
|---|---|
| 6 文件 / 1223 行新增 | PASS |
| 42 项 W8 测试全通过 | PASS |
| 349 项全量测试零回归 | PASS |
| 红线 grep 零违规 | PASS |
| 23 项严禁全遵守 | PASS |
| sandbox pass ≠ 生产可用（恒 False） | PASS |
| 不推 main | PASS |

**交付物**：
1. sandbox 子包 5 文件 + 测试 1 文件
2. 本报告
3. 分支 `qoder/m1-w8-sandbox-integration-skeleton`（commit `d6d84cb`，已推送）

**下一步**：推送分支 → Claude Code 反审 → ChatGPT 终审 → 吴哥拍板。
