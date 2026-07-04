# M1-W1/W2 服务骨架与 9080 只读召回 Qoder 报告

- **版本**: V1
- **报告日期**: 2026-07-04
- **分支**: `qoder/m1-w1-w2-factory-skeleton-recall`
- **基线**: W0.5 复核通过 commit `6ba819d`
- **当前 commit**: `9ed3062`
- **代码状态**: CODE_CANDIDATE（不得合并 main / 不得部署 / 不得启动 M1）

---

## 1. 分支与 Commit

| 项目 | 值 |
|---|---|
| 源分支 | `qoder/m1-w1-w2-factory-skeleton-recall` |
| 基线 commit | `6ba819d`（W0.5 模型路由 PASS） |
| W1/W2 commit | `9ed3062 feat(content-factory): W1 服务骨架 + W2 9080 只读召回适配` |
| 前序 commit | `56f3699`（W0.5 复核报告） |
| main 是否包含 | **否** |

---

## 2. Changed Files

全部 17 个文件均为**新增（A）**（含 W0.5 复核报告）：

```
A  M1_W0_5_MODEL_ROUTER_QODER_REVIEW_REPORT_V1.md
A  backend/app/content_factory/__init__.py
A  backend/app/content_factory/brief.py
A  backend/app/content_factory/factory.py
A  backend/app/content_factory/recall/__init__.py
A  backend/app/content_factory/recall/binding.py
A  backend/app/content_factory/recall/client.py
A  backend/app/content_factory/recall/filters.py
A  backend/app/content_factory/recall/recall_log.py
A  backend/app/content_factory/recall/results.py
A  backend/app/content_factory/recall/source_refs.py
A  backend/app/content_factory/schemas.py
A  backend/app/content_factory/staging.py
A  backend/app/content_factory/task_state.py
A  docs/M1/FACTORY_SKELETON_AND_RECALL_DESIGN_V0_1.md
A  tests/test_factory_brief.py
A  tests/test_factory_recall.py
```

---

## 3. Git Diff --stat

```
 M1_W0_5_MODEL_ROUTER_QODER_REVIEW_REPORT_V1.md     | 316 ++++++++++++
 backend/app/content_factory/__init__.py            |  40 ++
 backend/app/content_factory/brief.py               |  78 +++
 backend/app/content_factory/factory.py             | 121 +++++
 backend/app/content_factory/recall/__init__.py     |  35 ++
 backend/app/content_factory/recall/binding.py      | 109 +++++
 backend/app/content_factory/recall/client.py       |  91 ++++
 backend/app/content_factory/recall/filters.py      |  90 ++++
 backend/app/content_factory/recall/recall_log.py   |  98 ++++
 backend/app/content_factory/recall/results.py      |  56 +++
 backend/app/content_factory/recall/source_refs.py  |  32 ++
 backend/app/content_factory/schemas.py             | 112 +++++
 backend/app/content_factory/staging.py             |  49 ++
 backend/app/content_factory/task_state.py          |  89 ++++
 docs/M1/FACTORY_SKELETON_AND_RECALL_DESIGN_V0_1.md | 135 ++++++
 tests/test_factory_brief.py                        | 247 ++++++++++
 tests/test_factory_recall.py                       | 251 ++++++++++
 17 files changed, 1949 insertions(+)
```

---

## 4. Pytest 原始输出

```
platform win32 -- Python 3.14.5, pytest-9.1.0, pluggy-1.6.0
collected 133 items

tests/test_factory_brief.py (22 tests) — ALL PASSED
tests/test_factory_recall.py (19 tests) — ALL PASSED
tests/test_guardrails.py (43 tests) — ALL PASSED
tests/test_model_router.py (45 tests) — ALL PASSED

============================= 133 passed in 0.14s ==============================
```

---

## 5. W1 实现范围

| # | 允许做的事 | 状态 | 文件 |
|---|---|---|---|
| 1 | M1 文案加工厂服务骨架 | 已实现 | `content_factory/` 包 |
| 2 | Brief 数据结构 | 已实现 | `schemas.py: Brief` |
| 3 | 任务状态机 6 态 | 已实现 | `task_state.py: StateMachine` |
| 4 | factory 内部服务模块 | 已实现 | `factory.py: ContentFactory` |
| 5 | /factory/brief 代码结构草稿 | 骨架（未挂载路由） | `factory.py: process_brief` |
| 6 | 批量 Brief 输入结构 | 已实现 | `brief.py: parse_batch_briefs` |
| 7 | content_staging 私有目录设计 | 已实现 | `staging.py: ContentStaging` |
| 8 | trace_id / task_id / brief_id | 已实现 | `schemas.py: TraceContext` |
| 9 | mock 测试 | 已实现 | `test_factory_brief.py` 22 项 |
| 10 | 回滚说明 | 已验证 | `git revert 9ed3062` 完整回滚 |

---

## 6. W2 实现范围

| # | 允许做的事 | 状态 | 文件 |
|---|---|---|---|
| 1 | 9080 只读召回 client | 已实现（mock） | `recall/client.py: MockRecallClient` |
| 2 | 可配置、可 mock | 已实现 | `recall/client.py: RecallConfig(mock=True)` |
| 3 | 默认不真实访问 9080 | 已实现 | 默认 `base_url="mock"` |
| 4 | approved/candidate/missing/blocked 结构 | 已实现 | `recall/results.py: RecallStatus` |
| 5 | 白名单过滤 | 已实现 | `recall/filters.py: apply_filters` |
| 6 | 黑名单过滤 | 已实现 | 同上 |
| 7 | used_materials 绑定 | 已实现 | `recall/binding.py: bind_materials` |
| 8 | 缺料报告 | 已实现 | 桥接 `model_router.MissingMaterialReport` |
| 9 | source_refs 结构 | 已实现 | `recall/source_refs.py: SourceRef` |
| 10 | recall 日志结构 | 已实现 | `recall/recall_log.py: RecallLog` |

---

## 7. 是否挂载 FastAPI app

**否。** `content_factory/` 全目录无 FastAPI / APIRouter / include_router 引用。未修改 `main.py`。

---

## 8. 是否存在 /content/generate

**否。** grep 零命中。

---

## 9. 是否真实访问 9080

**否。** `RecallConfig` 默认 `mock=True`，`MockRecallClient` 返回预置脚本数据，无 HTTP 库引用。

---

## 10. 是否触达 9200

**否。** grep 零命中。

---

## 11. 是否写 approved / reindex / candidate_pool

**否。** 全目录无写入操作。`approved` 仅作为注释引用（"不写 approved"）。

---

## 12. used_materials 绑定测试

| 测试 | 结果 |
|---|---|
| 素材充分 → is_sufficient=True | PASS |
| 素材缺失 → MissingMaterialReport | PASS |
| HIGH_RISK 素材不足 → is_sufficient=False | PASS |
| BLOCKED 状态 → 拦截报告 | PASS |
| source_refs 绑定 | PASS |

---

## 13. 缺料报告测试

| 测试 | 结果 |
|---|---|
| RecallStatus.MISSING → 缺料报告 | PASS |
| 素材数量 < 最低要求 → 缺料报告 | PASS |
| RecallStatus.BLOCKED → 拦截报告（优先于缺料） | PASS |
| 缺料报告桥接 model_router.MissingMaterialReport | PASS |

---

## 14. 白名单 / 黑名单过滤测试

| 测试 | 结果 |
|---|---|
| 白名单保留 fact_card / compliance_rule | PASS |
| 白名单排除未知类型 | PASS |
| 自定义白名单 | PASS |
| 黑名单排除 draft / rejected / archived | PASS |
| 黑名单按 status 排除 | PASS |
| 空白名单+空黑名单 = 不过滤 | PASS |
| FilterReport 数量正确 | PASS |

---

## 15. 回滚说明

| 步骤 | 结果 |
|---|---|
| `git revert --no-commit 9ed3062` | 成功，无冲突 |
| diff --cached --stat | 16 files, 1633 deletions（与新增完全对称） |
| `content_factory/` 文件 | 全部清空 |
| 测试文件 | 全部清空 |
| 设计文档 | 已移除 |
| `git checkout 9ed3062 -- .` 恢复 | 成功恢复 |

**结论：`git revert 9ed3062` 可完整回滚，无库侧残留。**

---

## 16. 风险项

| # | 风险 | 等级 | 说明 |
|---|---|---|---|
| 1 | factory.process_brief 中模型出稿为 TODO | 低 | 骨架阶段设计如此，W3+ 工单实现 |
| 2 | 六硬门 G1-G6 为 TODO | 低 | W4 工单实现 |
| 3 | ContentStaging 为内存实现 | 低 | mock 阶段设计如此，后续工单持久化 |
| 4 | RecallLog 为内存实现 | 低 | 同上 |
| 5 | 最低素材数量要求为草案值 | 低 | M1 施工校准时调整 |

以上均为已标注的骨架/mock 阶段限制，非红线问题。

---

## 17. 结论

### **PASS**

**核心数据：**

- 17 个文件全部新增，0 修改已有代码，1949 行
- 133/133 测试全部通过（含原有 45 项 model_router + 43 项 guardrails 回归）
- 新增 W1 测试 22 项 + W2 测试 19 项
- grep 红线：/content/generate / 9200 / reindex / httpx / FastAPI 路由 — 全部零命中
- used_materials 绑定、缺料报告、白名单/黑名单过滤 — 全部测试通过
- `git revert 9ed3062` 完整回滚验证通过
- main 未受污染
- Qoder 未做修补——无需修补

**本结论只代表 W1/W2 服务骨架与召回适配通过，不代表 M1 启动。**

---

## 下一步纪律

1. 报告交付吴哥和 ChatGPT 复核；
2. ChatGPT 复核通过后，再决定是否允许进入 W3/W4；
3. W4 六硬门必须等 W1/W2 接口稳定后再写；
4. 不合并 main / 不部署 / 不启动 M1 / 不接真实发布 / 不打开 /content/generate；
5. Claude 暂不继续写，Coze 不碰代码只等报告。

**当前状态标记：**

- M1-W0.5：PASS
- M1-W1/W2：PASS（待终审）
- W3/W4：暂不允许
- M1：未启动
