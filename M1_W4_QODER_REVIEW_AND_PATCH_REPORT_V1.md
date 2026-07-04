# M1_W4_QODER_REVIEW_AND_PATCH_REPORT_V1

## Qoder 细化落码与独立复核报告

| 项目 | 内容 |
|---|---|
| 复核工单 | M1-W4 六硬门编排与候选裁决层 |
| Claude 分支 | `claude/m1-w4-gate-pipeline-skeleton` |
| Claude commit | `3eef133` |
| Qoder 复核分支 | `qoder/m1-w4-gate-review` |
| Qoder 复核 commit | `3ee9d74` |
| 基线 | `origin/qoder/m1-w3-draft-review @ 58bad6f`（W3 PASS） |
| 复核日期 | 2026-07-04 |

---

## 1. G0 远端对账

| 对账项 | 结果 |
|---|---|
| `git fetch --all --prune` | ✅ 完成 |
| `git ls-remote origin claude/m1-w4-gate-pipeline-skeleton` | ✅ 远端存在 `3eef133` |
| `git log --oneline -8` | ✅ `3eef133` 在列 |
| `git diff --stat 58bad6f..3eef133` | ✅ 10 files changed, 1150 insertions |
| commit `3eef133` 存在 | ✅ |
| 10 个 changed files 与 Claude 报告一致 | ✅ |
| 独立 pytest | ✅ 231/231 passed |
| 红线 grep | ✅ 全部零命中 |

**G0 结论：PASS ✅**

---

## 2. 分支与 Commit

```
3ee9d74 review(qoder): W4 复核补强 — 注释 9 态修正 + 4 项补强测试
3eef133 feat(content-factory): W4 六硬门编排与候选裁决层骨架
58bad6f review(qoder): M1-W3 复核报告 — PASS (195/195, 0 red-line, 4 补强测试)
```

---

## 3. Changed Files（Qoder delta on top of Claude）

| 文件 | 改动 |
|---|---|
| `backend/app/content_factory/schemas.py` | 注释 "8 态" → "9 态" 修正（W4 新增 GATE_BLOCKED） |
| `tests/test_w4_gate_pipeline.py` | +4 项补强测试 |

---

## 4. Git Diff --stat（Qoder 复核分支 vs W3 基线）

```
 backend/app/content_factory/factory.py             |  41 +-
 backend/app/content_factory/gates/__init__.py      |  66 +++
 backend/app/content_factory/gates/fact_ref.py      |  83 ++++
 backend/app/content_factory/gates/pipeline.py      | 174 ++++++++
 backend/app/content_factory/gates/review_package.py |  89 +++++
 backend/app/content_factory/gates/rules.py         | 153 +++++++
 backend/app/content_factory/gates/schemas.py       | 148 +++++++
 backend/app/content_factory/schemas.py             |  10 +-
 backend/app/content_factory/task_state.py          |  13 +-
 tests/test_w4_gate_pipeline.py                     | 444 +++++++++++++++++++++
 10 files changed, 1210 insertions(+), 11 deletions(-)
```

---

## 5. 是否修补

**是。** Qoder 在 Claude 骨架基础上做了 2 处修补：

1. **注释修正**：`schemas.py` 文件头注释 "8 态" → "9 态"（W4 新增 GATE_BLOCKED 第 9 态）
2. **+4 项补强测试**：gate_blocked terminal / review_package slots / gate_summary / conditional E2E

---

## 6. 修补 Commit

```
3ee9d74 review(qoder): W4 复核补强 — 注释 9 态修正 + 4 项补强测试
```

---

## 7. Pytest 原始输出

```
============================= 235 passed in 0.31s =============================
```

235 = 195（W3 基线）+ 36（Claude W4 新增）+ 4（Qoder 补强）

---

## 8. 红线 Grep

在 `backend/app/content_factory/` 范围内逐项 grep：

| 红线 | Pattern | 命中 |
|---|---|---|
| `/content/generate` | `/content/generate` | 0 ✅ |
| 真实 9200 | `9200` | 0 ✅ |
| reindex | `reindex` | 0 ✅ |
| httpx | `httpx` | 0 ✅ |
| FastAPI 挂载 | `include_router\|FastAPI\|APIRouter` | 0 ✅ |
| `approved=True` | `approved\s*=\s*True` | 0 ✅ |
| candidate_pool | `candidate_pool` | 0 ✅ |
| site_published | `site_published` | 0 ✅ |
| `publish_allowed=True` | `publish_allowed\s*=\s*True` | 0 ✅ |
| 真实模型 API | `openai\|anthropic\|dashscope\|API_KEY` | 0 ✅ |

---

## 9. W4 链路复核

| 复核项 | 结果 |
|---|---|
| W4 只做六硬门候选裁决层，不进入 W5 | ✅ `review_package.py` 只定结构，不做前台/人审动线 |
| 接入 W3 DraftCandidate | ✅ `pipeline.run(candidate: DraftCandidate)` |
| 三版稿逐版执行 G1-G6 | ✅ `for v in candidate.versions` 逐版过门 |
| conditional_pass 只进人审，不自动发布 | ✅ `NEEDS_HUMAN_REVIEW` + `must_sign=True` + `publish_allowed=False` |
| warning 不阻断 ready_for_review | ✅ `_aggregate()` 只看 fail 分 clean/failed |
| loop ≤ 3 圈 | ✅ `MAX_LOOP_ROUNDS = 3` |
| 3 圈仍 fail → blocked | ✅ `test_loop_caps_at_3_rounds` |
| publish_allowed/writes_approved 恒 False | ✅ 三层常量 `init=False`：CandidateGateReport / ReviewPackagePre / RouterResult |
| 无真实模型 API | ✅ |
| 无真实 9080 | ✅ |
| 无 FastAPI / APIRouter | ✅ |
| 无 /content/generate | ✅ |
| 无 9200 / reindex / approved / candidate_pool / site_published | ✅ |

---

## 10. G1-G6 逐门复核

| 门 | 实现 | 判定逻辑 | 测试覆盖 |
|---|---|---|---|
| **G1 合规红线** | `gate_g1()` + `prescan_g1` | 禁用词→FAIL；谨慎词→CONDITIONAL_PASS | ✅ banned / caution / redline-blocks |
| **G2 状态越界** | `gate_g2()` | 玄学/转运/宿命词→FAIL | ✅ 4 参数化 bad + 正常状态语言 pass |
| **G3 事实引用** | `MockG3Adjudicator` | 无源事实句→FAIL；检测缺要素→FAIL | ✅ unsourced / detection-missing / complete / injectable |
| **G4 平台结构** | `gate_g4()` | 缺必需结构→FAIL；缺可选→WARNING；非结构→routed_to | ✅ structure-fail / routes-not-fail / optional-warning |
| **G5 品牌一致** | `gate_g5()` | 串品牌/串产品→FAIL | ✅ other-brand / other-product / dfd-pass |
| **G6 格式完整** | `gate_g6()` | 缺正文/ids/审计→FAIL | ✅ empty-text / missing-ids / missing-audit / complete |

---

## 11. G3 FactRefAdjudicator 接口复核

| 复核项 | 结果 |
|---|---|
| `FactRefAdjudicator` 为 Protocol | ✅ `class FactRefAdjudicator(Protocol)` |
| `adjudicate(text, materials) → GateResult` | ✅ |
| `MockG3Adjudicator` 为默认实现 | ✅ 注入点不变，替换实现即可 |
| W3 启发式作为输入信号（非 G3 本体） | ✅ `audit_sentences()` 结果封装在正式接口内 |
| 不把 W3 启发式写死为正式规则 | ✅ `test_g3_uses_injectable_adjudicator_not_hardwired` |
| 检测完整性三要素 | ✅ 方法/编号/机构 |

---

## 12. G4 只判结构与 routed_to 复核

| 复核项 | 结果 |
|---|---|
| G4 只检查平台必需/可选结构项 | ✅ `_PLATFORM_REQUIRED` / `_PLATFORM_OPTIONAL` |
| 非结构信号不由 G4 出 fail | ✅ `_ROUTE_SIGNALS` 只进 `routed_to` |
| 合规问题路由到 G1 | ✅ `test_g4_does_not_adjudicate_compliance_only_routes` |
| 品牌/状态问题路由到 G5/G2 | ✅ `test_g4_routes_brand_and_state_issues` |
| G4 不扩权成事实/合规/品牌裁决器 | ✅ |

---

## 13. Loop ≤ 3 圈复核

| 复核项 | 结果 |
|---|---|
| `MAX_LOOP_ROUNDS = 3` | ✅ |
| G1 红线 fail 即刻 blocked（不重试） | ✅ `has_g1_redline_fail` 短路 |
| 无 revise_callback → 1 圈定 blocked | ✅ `test_no_callback_single_round_blocked` |
| revise 永不修好 → 恰好 3 圈 blocked | ✅ `test_loop_caps_at_3_rounds`（calls=6 = 2次×3版） |
| revise 第 2 圈修好 → converged | ✅ `test_loop_converges_when_revised` |

---

## 14. conditional_pass / warning / fail 聚合复核

| 场景 | 预期 | 测试 |
|---|---|---|
| 全 clean + 仅 warning | `READY_FOR_REVIEW` | ✅ `test_warning_only_is_ready` |
| 全 clean + 含 conditional | `NEEDS_HUMAN_REVIEW` + `must_sign` | ✅ `test_conditional_needs_human_review_must_sign` |
| 部分 fail、部分 clean | `NEEDS_REVISION` | ✅ aggregate 逻辑 |
| 全 fail | `BLOCKED` | ✅ `test_g1_redline_blocks_version_immediately` |

---

## 15. 审读包前置结构复核

| 复核项 | 结果 |
|---|---|
| `ReviewPackagePre` 数据结构 | ✅ content_id / brief_id / trace_id / review_status / must_sign / version_slots |
| `VersionReviewSlot` 单版槽位 | ✅ version_kind / text / used_materials_ids / gate_summary / loop_status / is_reviewable |
| `publish_allowed / writes_approved` 恒 False | ✅ `init=False` 常量 |
| `build_review_package_pre()` 装配 | ✅ 按 kind 对齐文本 + 6 门摘要 |
| Qoder 补强：3 slots + gate_summary 完整性 | ✅ |

---

## 16. 是否触达 W5

**否。**

- `review_package.py` 只定义数据结构和装配函数
- 无前台渲染、无人审按钮、无审读台 UI
- `factory.py` Step 5 仍为 `TODO(W5)`
- 无任何"人审动线"实现

---

## 17. 是否接真实模型/9080

**否。**

- 模型层：全部使用 `MockModelClient`
- 召回层：全部使用 `MockRecallClient`
- 无 `httpx / requests / openai / anthropic / dashscope` 等

---

## 18. 回滚说明

| 回滚操作 | 命令 |
|---|---|
| 丢弃 Qoder 复核补强 | `git revert 3ee9d74` |
| 丢弃 Claude W4 骨架 | `git revert 3eef133` |
| 完全回退到 W3 PASS | `git checkout 58bad6f` |

Qoder 分支 `qoder/m1-w4-gate-review` 不影响 `main` 或其他已 PASS 分支。

---

## 19. 风险项

| 风险 | 等级 | 说明 |
|---|---|---|
| G1-G6 为 mock 词表 | ⚠️ 已知 | 骨架期占位，正式规则集需外置配置+版本化 |
| G3 MockG3Adjudicator 仍含启发式 | ⚠️ 已知 | 封装在正式 Protocol 接口内，替换实现即可 |
| schemas.py 注释 8→9 态不一致 | ✅ 已修 | Qoder 已统一为 "9 态" |
| G4 平台结构检查为简单字符串匹配 | ⚠️ 已知 | 骨架占位，正式实现需更精细的结构解析 |

---

## 20. 结论

### **PASS ✅**

| 维度 | 判定 |
|---|---|
| G0 远端对账 | PASS ✅ |
| W4 链路（13 项） | PASS ✅ |
| G1-G6 逐门（6 门） | PASS ✅ |
| G3 FactRefAdjudicator 接口 | PASS ✅ |
| G4 只判结构 + routed_to | PASS ✅ |
| Loop ≤ 3 圈 | PASS ✅ |
| conditional/warning/fail 聚合 | PASS ✅ |
| 审读包前置结构 | PASS ✅ |
| 不触达 W5 | PASS ✅ |
| 不接真实模型/9080 | PASS ✅ |
| 红线 grep | PASS ✅（全零） |
| pytest | PASS ✅（235/235） |
| Qoder 补强 | 2 处修补 + 4 项测试，全通过 |

**W4 骨架 + Qoder 复核已就绪，交 Claude Code 反审。**
