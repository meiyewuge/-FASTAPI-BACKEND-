# M1_W3_QODER_REVIEW_AND_PATCH_REPORT_V1

## Qoder 细化落码与独立复核报告

| 项目 | 内容 |
|---|---|
| 复核工单 | M1-W3 草稿生成与模型路由接线 |
| Claude 分支 | `claude/m1-w3-draft-generation-skeleton` |
| Claude commit | `dd0c371` |
| Qoder 复核分支 | `qoder/m1-w3-draft-review` |
| Qoder 复核 commit | `32bea47` |
| 基线 | `origin/qoder/m1-w1-w2-factory-skeleton-recall @ f0f1e2b`（W1/W2 PASS） |
| 复核日期 | 2026-07-04 |

---

## 1. G0 远端对账

| 对账项 | 结果 |
|---|---|
| `git fetch --all --prune` | ✅ 完成 |
| `git ls-remote origin claude/m1-w3-draft-generation-skeleton` | ✅ 远端存在 |
| `git log --oneline -5` | ✅ `dd0c371` 在列 |
| `git diff --stat f0f1e2b..dd0c371` | ✅ 10 files changed, 835 insertions |
| commit `dd0c371` 存在 | ✅ |
| 10 个 changed files 与 Claude 报告一致 | ✅ |
| 独立 pytest | ✅ 191/191 passed |
| 红线 grep | ✅ 全部零命中 |

**G0 结论：PASS ✅**

---

## 2. 分支与 Commit

```
32bea47 review(qoder): W3 复核补强 — 注释 8 态修正 + 4 项补强测试
dd0c371 feat(content-factory): W3 草稿生成与模型路由接线骨架
f0f1e2b review(qoder): Patch D 修补报告 — PASS (160/160, 0 red-line)
```

---

## 3. Changed Files（Qoder delta on top of Claude）

| 文件 | 改动 |
|---|---|
| `backend/app/content_factory/schemas.py` | 注释 "7 态" → "8 态" 修正 |
| `backend/app/content_factory/task_state.py` | 注释 "7 态" → "8 态" 修正 |
| `tests/test_w3_draft_generation.py` | +4 项补强测试 |

---

## 4. Git Diff --stat（Qoder 复核分支 vs W1/W2 基线）

```
 backend/app/content_factory/drafting/__init__.py   |  46 +++
 backend/app/content_factory/drafting/generator.py  | 168 +++++++++
 backend/app/content_factory/drafting/new_fact_guard.py | 43 +++
 backend/app/content_factory/drafting/schemas.py    |  89 +++++
 backend/app/content_factory/drafting/sentence_refs.py | 111 ++++++
 backend/app/content_factory/factory.py             |  52 ++-
 backend/app/content_factory/recall/filters.py      |  18 +
 backend/app/content_factory/schemas.py             |   6 +-
 backend/app/content_factory/task_state.py          |   7 +-
 tests/test_w3_draft_generation.py                  | 384 +++++++++++++++++++++
 10 files changed, 912 insertions(+), 12 deletions(-)
```

---

## 5. 是否修补

**是。** Qoder 在 Claude 骨架基础上做了 3 处修补：

1. **注释修正**：`schemas.py` + `task_state.py` 注释从 "7 态" 更正为 "8 态"（BLOCKED_DRAFT 是第 8 态）
2. **+4 项补强测试**：partial block / terminal state / direction_hint prompt isolation / all-blocked e2e

---

## 6. 修补 Commit

```
32bea47 review(qoder): W3 复核补强 — 注释 8 态修正 + 4 项补强测试
```

---

## 7. Pytest 原始输出

```
============================= 195 passed in 0.26s =============================
```

195 = 160（W1/W2 基线）+ 31（Claude W3 新增）+ 4（Qoder 补强）

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
| `publish_allowed=True` | `publish_allowed\s*=\s*True` | 0 ✅ |
| 真实模型 API | `openai\|anthropic\|dashscope\|API_KEY` | 0 ✅ |
| G1-G6 正式裁决器 | `G1\|G2\|G3\|G4\|G5\|G6`（在 drafting/ 内） | 0 ✅ |

---

## 9. W3 链路复核

| 复核项 | 结果 |
|---|---|
| W3 只接草稿生成，不进入 W4 | ✅ `factory.py` Step 4 仍为 TODO(W4)，未实现 gate_pipeline |
| 真正接入 W0.5 model_router | ✅ `DraftGenerator` 持有 `ModelRouter`，调用 `generate_draft()` |
| 只在 used_materials 充分时生成 draft_candidate | ✅ factory Step 2.5 缺料停单 + generator 防御性空素材检查 |
| 无 recall_client 继续停单 | ✅ Patch D 逻辑不变，`recall_client=None → HALTED` |
| 空素材停单 | ✅ bind_materials.is_sufficient=False → HALTED |
| 黑名单过滤后不足停单 | ✅ apply_filters 后 bind_materials 重新判定 |
| direction_hint 不进 used_materials | ✅ direction_hint 只存 Brief 字段，不进召回关键词也不进绑定 |
| daily_*/webintel_*/crawl_* 前缀过滤 | ✅ `DEFAULT_BLACKLIST_PREFIXES` 已实现 + 测试覆盖 |
| Kimi/platform_inspiration/raw_draft 不得作事实源 | ✅ 黑名单精确匹配 + fail-closed |
| 三版稿共用同一组 used_materials | ✅ generator.generate 传同一 `bound.materials` |

---

## 10. 三版稿复核

| 复核项 | 结果 |
|---|---|
| 三版枚举 | ✅ `PROFESSIONAL / STATE_AESTHETIC / PLATFORM_REWRITE` |
| 每版独立生成 | ✅ `_one_version()` 按 DraftVersionKind 逐个调用 model_router |
| 每版独立拦截 | ✅ new_fact_guard + sentence_refs 逐版审计 |
| 全部 OK → DRAFT_CANDIDATE | ✅ |
| 部分 OK → 仍 DRAFT_CANDIDATE | ✅ Qoder 补强测试验证 |
| 全部被拦 → BLOCKED → BLOCKED_DRAFT 终态 | ✅ |

---

## 11. source_refs 句级溯源复核

| 复核项 | 结果 |
|---|---|
| SentenceRef 结构 | ✅ sentence / is_fact / source_material_ids |
| SentenceAudit 结构 | ✅ refs / passed / violations |
| 事实句判定 | ✅ `classify_fact()` — 含数字或事实标记词 |
| 溯源绑定 | ✅ `attach_refs()` — ID 内嵌引用 + 内容片段重合（≥8 字） |
| 无源事实句 → 整版拒绝 | ✅ `audit_sentences()` violations → BLOCKED_UNSOURCED_FACT |
| 支撑后续 G3 | ✅ 数据结构（SentenceRef/SentenceAudit）可被 G3 正式裁决器消费 |

**风险项**：事实句识别为 mock 启发式（数字/标记词），非正式 G3 裁决器。Claude 报告已声明，Qoder 确认不越权。

---

## 12. 模型新增事实拦截复核

| 复核项 | 结果 |
|---|---|
| detect_new_facts 实现 | ✅ 抽取数字串（≥2 位）+ 报告编号（字母数字 ≥6 位） |
| 未在素材中出现 → 判定新增 | ✅ |
| 新增事实 → BLOCKED_NEW_FACT | ✅ |
| 素材中已有 → 不算新增 | ✅ 测试 `test_number_present_in_material_not_new` |

**风险项**：拦截依赖数字/编号 token 启发式，不能拦截"文字性编造事实"。Claude 报告已声明，Qoder 确认不冒充完整事实审查。

---

## 13. 黑名单前缀匹配复核

| 复核项 | 结果 |
|---|---|
| `DEFAULT_BLACKLIST_PREFIXES` | ✅ `daily_ / webintel_ / crawl_` |
| `_hits_blacklist_prefix()` | ✅ `any(value.startswith(p))` |
| material_type + source_type 双检 | ✅ |
| 6 个变体参数化测试 | ✅ 全通过 |
| source_type 前缀测试 | ✅ `crawl_raw_feed → 拒绝` |
| E2E 前缀素材不进 used_materials | ✅ |

---

## 14. direction_hint 隔离复核

| 复核项 | 结果 |
|---|---|
| direction_hint 存 Brief 字段 | ✅ |
| 不进召回关键词 | ✅ `brief.raw_text.split()[:5]` 不含 direction_hint |
| 不进 used_materials | ✅ 绑定只来自 bind_materials |
| 不进模型提示词素材区 | ✅ Qoder 补强测试验证 `build_prompt()` 无 direction_hint |

---

## 15. 是否触达 W4

**否。**

- `factory.py` Step 4 仍为 `TODO(W4): gate_results = gate_pipeline(text, task)`
- `drafting/` 子包内无 G1-G6 正式裁决器
- `ModelRouter.gate_pipeline` 仍为 `None`（只有 G1 prescan 兜底）
- 六硬门挂接点保留但未激活

---

## 16. 是否接真实模型/9080

**否。**

- 模型层：全部使用 `MockModelClient`，无 `openai / anthropic / dashscope` 等真实 API
- 召回层：全部使用 `MockRecallClient`，无真实 9080 调用
- 无 `httpx / requests` 等 HTTP 库引入

---

## 17. 回滚说明

| 回滚操作 | 命令 |
|---|---|
| 丢弃 Qoder 复核补强 | `git revert 32bea47` |
| 丢弃 Claude W3 骨架 | `git revert dd0c371` |
| 完全回退到 W1/W2 PASS | `git checkout f0f1e2b` |

Qoder 分支 `qoder/m1-w3-draft-review` 不影响 `main` 或 `qoder/m1-w1-w2-factory-skeleton-recall`。

---

## 18. 风险项

| 风险 | 等级 | 说明 |
|---|---|---|
| 句级溯源为 mock 启发式 | ⚠️ 已知 | 事实句判定靠数字/标记词，W4 正式 G3 替换 |
| 新增事实拦截靠 token | ⚠️ 已知 | 只拦数字/编号，文字编造拦不到，W4 替换 |
| 8 态注释不一致 | ✅ 已修 | Qoder 已将 schemas.py / task_state.py 注释统一为 "8 态" |

---

## 19. 结论

### **PASS ✅**

| 维度 | 判定 |
|---|---|
| G0 远端对账 | PASS ✅ |
| W3 链路（10 项） | PASS ✅ |
| 三版稿结构 | PASS ✅ |
| source_refs 句级溯源 | PASS ✅（骨架级，非正式 G3） |
| 模型新增事实拦截 | PASS ✅（骨架级，非完整审查） |
| 黑名单前缀匹配 | PASS ✅ |
| direction_hint 隔离 | PASS ✅ |
| 不触达 W4 | PASS ✅ |
| 不接真实模型/9080 | PASS ✅ |
| 红线 grep | PASS ✅（全零） |
| pytest | PASS ✅（195/195） |
| Qoder 补强 | 3 处修补 + 4 项测试，全通过 |

**W3 骨架 + Qoder 复核已就绪，交 Claude Code 反审。**
