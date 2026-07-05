# M1_W6_QODER_REVIEW_AND_PATCH_REPORT_V1

## Qoder 细化落码与独立复核报告

| 项目 | 内容 |
|---|---|
| 复核工单 | M1-W6 产线日报与运行观测 |
| Claude 分支 | `claude/m1-w6-daily-observability-skeleton` |
| Claude commit | `f9e486c` |
| Qoder 复核分支 | `qoder/m1-w6-review` |
| Qoder 复核 commit | `be4c58a` |
| 基线 | `origin/qoder/m1-w5-review @ ca98d69`（W5 PASS） |
| 复核日期 | 2026-07-04 |

---

## 1. G0 远端对账

| 对账项 | 结果 |
|---|---|
| `git fetch --all --prune` | ✅ 完成 |
| `git ls-remote` | ✅ 远端存在 `f9e486c` |
| `git log --oneline -8` | ✅ `f9e486c` 在列 |
| `git diff --stat ca98d69..f9e486c` | ✅ 5 files changed, 568 insertions |
| 独立 pytest | ✅ 274/274 passed |
| 红线 grep | ✅ 全部零命中 |

**G0 结论：PASS ✅**

---

## 2. 分支与 Commit

```
be4c58a review(qoder): W6 复核补强 — 3 项补强测试
f9e486c feat(content-factory): W6 产线日报与运行观测骨架
ca98d69 review(qoder): M1-W5 复核报告 — PASS (257/257)
```

---

## 3. Changed Files（Qoder delta）

| 文件 | 改动 |
|---|---|
| `tests/test_w6_daily_observability.py` | +3 项补强测试 |

---

## 4. Git Diff --stat（vs W5 基线）

```
 backend/app/content_factory/observability/__init__.py  |  35 +++
 backend/app/content_factory/observability/observer.py  |  59 ++++
 backend/app/content_factory/observability/report.py    | 107 +++++++
 backend/app/content_factory/observability/schemas.py   | 140 +++++++++
 tests/test_w6_daily_observability.py                   | 279 +++++++++++++++++
 5 files changed, 620 insertions(+)
```

---

## 5. 是否修补

**是。** Qoder 新增 3 项补强测试：brief_count 去重 / G1/G3 fail 分母校验 / draft vs gate blocked 独立计数。

---

## 6. 修补 Commit

```
be4c58a review(qoder): W6 复核补强
```

---

## 7. Pytest 原始输出

```
============================= 277 passed in 0.30s =============================
```

277 = 257（W5 基线）+ 17（Claude W6）+ 3（Qoder 补强）

---

## 8. 红线 Grep

| 红线 | 命中 |
|---|---|
| `/content/generate` / FastAPI / APIRouter | 0 ✅ |
| 真实 9200 / reindex / approved / candidate_pool / site_published | 0 ✅ |
| httpx / 真实模型 API | 0 ✅ |
| scheduler / celery / apscheduler | 0 ✅ |
| `publish_allowed=True` / `writes_approved=True` | 0 ✅ |

---

## 9. W6 链路复核（30 项）

| # | 复核项 | 结果 |
|---|---|---|
| 1 | W6 只做产线日报与运行观测，不进 W7 | ✅ |
| 2 | 只读聚合 FactoryResult，不改动 | ✅ `test_observe_does_not_mutate_result` |
| 3 | 不接真实数据库 | ✅ 纯内存 `List[RunObservation]` |
| 4 | 不接真实监控平台 | ✅ |
| 5 | 不接真实定时任务 | ✅ 无 scheduler/celery |
| 6 | 不接真实发布池 | ✅ |
| 7 | marked_ready 只计备发标记数 | ✅ 指标名 `marked_ready_to_publish_count` |
| 8 | 日报无 published/approved/site_published | ✅ `test_no_publish_no_approved_metric_names` |
| 9 | candidate_review ≠ approved | ✅ 计 `review_state_counts`，不称 approved |
| 10 | draft_candidate_count 只表示出候选进审读 | ✅ `PACKAGED` 计数 |
| 11 | gate_blocked_count 只统计门检拦截 | ✅ `GATE_BLOCKED` 计数 |
| 12 | draft_blocked_count 只统计 W3 草稿拦截 | ✅ `BLOCKED_DRAFT` 计数 |
| 13 | missing_materials_count 统计缺料停单 | ✅ `HALTED_MISSING_MATERIALS` |
| 14 | needs_human_review_count = needs_human + must_sign | ✅ |
| 15 | rejected_for_revision_count 统计驳回修改 | ✅ |
| 16 | brief_count 与 run_count 区分 | ✅ brief_id 去重 vs 不去重 |
| 17 | no_recall_client 只统计 recall_client_not_configured | ✅ `had_recall_client=False` |
| 18 | missing_after_filter 只统计有 recall_client 但仍缺料 | ✅ |
| 19 | high_g1_g3_fail 按过门运行比例 | ✅ `loop_rounds_used > 0` 为分母 |
| 20 | loop_exhausted 统计 3 圈耗尽未收敛 | ✅ `rounds >= 3 and not converged` |
| 21 | human_review_backlog 按 needs_human + must_sign | ✅ |
| 22 | G3 门检与 W3 草稿拦截不重复计 | ✅ 独立指标，独立 RunOutcome |
| 23 | 异常阈值可配置 | ✅ `AnomalyThresholds` dataclass |
| 24 | mock 日报输出为 dataclass/dict | ✅ `DailyReport.to_dict()` |
| 25 | 无真实模型 API | ✅ |
| 26 | 无真实 9080 | ✅ |
| 27 | 无 FastAPI / APIRouter | ✅ |
| 28 | 无 /content/generate | ✅ |
| 29 | 无 9200/reindex/approved/candidate_pool/site_published | ✅ |
| 30 | 274/274 独立复现 | ✅ 277/277（含补强） |

---

## 10. 日报统计结构复核

✅ `DailyReport` 含 `date` / `metrics`（9 项）/ `by_outcome` / `review_state_counts` / `anomalies`，`to_dict()` 输出完整 dict。

---

## 11. 7 类指标复核

| 指标 | 来源 | 口径 |
|---|---|---|
| brief_count | `brief_id` 去重 | 下单 brief 数 |
| run_count | `observations` 总数 | 运行总次数 |
| draft_candidate_count | PACKAGED outcome | 出候选进审读 |
| gate_blocked_count | GATE_BLOCKED outcome | W4 门检拦截 |
| draft_blocked_count | BLOCKED_DRAFT outcome | W3 草稿拦截 |
| missing_materials_count | HALTED outcome | 缺料停单 |
| needs_human_review_count | queue needs_human + must_sign | 人审积压 |
| marked_ready_to_publish_count | queue marked_ready | 备发标记（≠发布量） |
| rejected_for_revision_count | queue rejected | 驳回修改 |

---

## 12. 5 类异常观测复核

| 异常 | 触发条件 | 阈值 |
|---|---|---|
| NO_RECALL_CLIENT | `had_recall_client=False` | ≥1 即触发，severity=high |
| MISSING_AFTER_FILTER | HALTED + had_recall_client | `missing_after_filter_min`（默认 1） |
| HIGH_G1_G3_FAIL | g1g3/过门运行 ≥ 阈值 | `g1_g3_fail_rate`（默认 0.30） |
| LOOP_EXHAUSTED | rounds ≥ 3 + not converged | `loop_exhausted_min`（默认 1） |
| HUMAN_REVIEW_BACKLOG | needs_human + must_sign ≥ 阈值 | `human_backlog`（默认 5） |

---

## 13. G3 门检口径 vs W3 草稿拦截口径复核

**关键发现：两者严格分离，不重复计。**

| 层级 | 拦截位置 | RunOutcome | 指标 |
|---|---|---|---|
| W3 草稿拦截 | DraftGenerator → sentence_audit / new_fact_guard | `BLOCKED_DRAFT` | `draft_blocked_count` |
| W4 G3 门检 | GatePipeline → G3 FactRefAdjudicator | `GATE_BLOCKED` | `gate_blocked_count` + `g3_fail_count` |

W3 先拦"无源事实句"，所以 W6 的 `g3_fail_count` 主要统计 W4 G3 的"检测三要素不全"（检测宣称缺"机构"要素）。两者由 `RunOutcome` 枚举值严格区分。

测试文件第 38-42 行有明确注释说明此口径。

---

## 14. marked_ready_to_publish 非发布量复核

✅ 指标名为 `marked_ready_to_publish_count`，注释明确"备发标记数，≠发布量"。日报不产出 `published_count`。

---

## 15. candidate_review 非 approved 复核

✅ 计 `review_state_counts`，字段名不含 approved。`test_no_publish_no_approved_metric_names` 验证日报无 approved 口径。

---

## 16. mock 日报输出复核

✅ `DailyReport.to_dict()` 输出标准 dict，含 date / metrics / by_outcome / review_state_counts / anomalies。无真实持久化。

---

## 17. 是否触达 W7

**否。** 无真实日报持久化、无真实定时任务、无真实监控上报。

---

## 18. 是否接真实监控/数据库/定时任务

**否。** 全部内存聚合，无 scheduler/celery/database import。

---

## 19. 是否接真实发布/模型/9080

**否。** 全部 mock，无真实后端接入。

---

## 20. 回滚说明

| 操作 | 命令 |
|---|---|
| 丢弃 Qoder 补强 | `git revert be4c58a` |
| 丢弃 Claude W6 骨架 | `git revert f9e486c` |
| 完全回退到 W5 PASS | `git checkout ca98d69` |

---

## 21. 风险项

| 风险 | 等级 | 说明 |
|---|---|---|
| 日报持久化未接入 | ⚠️ 已知 | 纯内存聚合，W7 接入持久化存储 |
| 定时任务未接入 | ⚠️ 已知 | 手动调用 `build_daily_report`，W7 接入真实调度器 |
| 监控上报未接入 | ⚠️ 已知 | AnomalyFlag 仅内存，W7 接入真实监控平台 |
| 异常阈值待校准 | ⚠️ 已知 | 默认值为草案，M1 正式施工阶段需校准 |

---

## 22. 结论

### **PASS ✅**

| 维度 | 判定 |
|---|---|
| G0 远端对账 | PASS ✅ |
| W6 链路（30 项） | PASS ✅ |
| 日报统计结构 | PASS ✅ |
| 7 类指标口径 | PASS ✅ |
| 5 类异常观测 | PASS ✅ |
| G3 门检 vs W3 草稿拦截分离 | PASS ✅ |
| marked_ready 非发布量 | PASS ✅ |
| candidate_review 非 approved | PASS ✅ |
| mock 日报输出 | PASS ✅ |
| 不触达 W7 | PASS ✅ |
| 不接真实监控/数据库/定时任务 | PASS ✅ |
| 不接真实发布/模型/9080 | PASS ✅ |
| 红线 grep | PASS ✅（全零） |
| pytest | PASS ✅（277/277） |
| Qoder 补强 | 3 项测试，全通过 |

**W6 骨架 + Qoder 复核已就绪，交 Claude Code 反审。**
