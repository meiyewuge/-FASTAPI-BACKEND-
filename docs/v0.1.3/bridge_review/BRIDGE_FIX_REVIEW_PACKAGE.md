# 桥接修复 · 审查包（issue → action_task）

> 审查对象：上一版代码 HEAD `2949888` → 本次桥接修复 HEAD `5484630`
> 审查范围：`git diff 2949888..5484630`（仅 backend）
> 仓库：`-FASTAPI-BACKEND-` ｜ 分支：`store-manager-v0.1.3-backend`（未 push）

## 1. 修复背景
四闸门第一次重跑 28 PASS / 8 FAIL：18081 部署通过，但**四闸门验收不通过**。
诊断 issue 与 `today_action` 都已生成，但 `today-tasks` 为空 —— 今日任务、P0 限流、完成、幂等、复盘、明日 3 件事全部无法验收。"店长工作台"退化成了"诊断报告"。

## 2. 根因
诊断主流程 `create_diagnosis` 生成 `store_diagnosis_issue`（含 `today_action`），但**从未写入 `store_action_task`**；而 `today-tasks` 读的是 `store_action_task`。两表之间缺少桥接，导致诊断驱动的今日任务永远为空（此前 today-tasks 仅可能有 customer_ops 任务）。

## 3. 修复目标
1. 诊断生成 issue 后，据 `issue.today_action` 自动生成对应 `store_action_task`；
2. `today-tasks / generate` 聚合 `diagnosis_issue` + `customer_ops` 两类来源；
3. P0 限流（≤3）正确，投诉/退款/差评永远 P0；
4. 重复调用幂等，不丢 `done/completed` 状态；
5. 复盘后明日 3 件事不为空；
6. 补四闸门验收脚本与单元 smoke。

## 4. 变更文件清单（git diff --stat 2949888..5484630，backend）
```
db_v013.py        | 15 +    （force_p0 列 + 迁移）
pipeline_v013.py  |  3 +    （诊断后调用桥接）
tasks_v013.py     | 140 ±   （桥接/聚合/全局P0限流）
four_gate_check_v013.py | 151 + （新增·第四闸门脚本）
smoke_app_level_v013.py |  4 +
smoke_test_v013.py      | 11 ±
6 files changed, 288 insertions(+), 36 deletions(-)
```

## 5. issue → action_task 桥接逻辑
新增 `tasks_v013.sync_diagnosis_tasks(conn, store_id, report_date)`：
- 取该 `store_id + report_date` 最新一份诊断的 **top3 问题**（`store_diagnosis_issue` 按 `sort_order, severity` 取 3）；
- 每个 issue → 一条 `store_action_task`：
  - `source_type='diagnosis_issue'`，`source_id='diagnosis_issue:{issue_id}'`（幂等键）；
  - `title=issue.issue_name`，`description=issue.today_action`（缺省回退 issue_name）；
  - `priority=issue.priority`（0/1，severity≥8 → P0）；`status='pending'`，`force_p0=0`；
- **幂等**：`source_id` 已存在则只更新 title/description/priority，**保留 status/completed_at/review_note**；不再属于 top3 的旧诊断任务（未完成）清除；
- 在 `pipeline.create_diagnosis` 提交 issue 后立即调用 → **POST monthly-diagnoses 即落库任务，today-tasks 非空**。

## 6. 两类任务聚合（diagnosis_issue + customer_ops）
`generate_today_tasks`：
1. 先 `sync_diagnosis_tasks`（诊断任务）；
2. 收集 customer_ops 候选（红色预警 / 可成交需求 / 项目消耗，按顾客合并）→ upsert（`source_id='customer:{cid}'`）；
3. 全局 P0 限流；
4. `get_today_tasks` 返回两类合并结果（按 `priority ASC, keep_red_tag DESC, id`）。
`get_today_tasks` 透传 `action`（诊断任务为 today_action 文本，顾客任务为合并项 JSON）。

## 7. P0 限流与 force_p0
- `store_action_task` 新增 `force_p0`：投诉/退款/差评（`COMPLAINT_TYPES`）的顾客合并卡 `force_p0=1`，**永远 P0、不受限流**。
- `_apply_global_p0_limit`：取当日 `priority=0 且未完成` 任务；`force_p0=1` 全部保留为 P0；其余按「红标 > 合并数 > 时效(id)」排序，保留 `3 - len(force)` 条为 P0，**超限降为 P1 并 `is_throttled_to_p1=1`（保留红标 keep_red_tag）**；
- 幂等：每次按基准优先级重算，可重复调用结果一致。

## 8. done/completed 幂等保留
- 桥接与聚合均**以 source_id upsert**，UPDATE 只刷新展示/优先级字段，**不触碰 status/completed_at/review_note**；
- 本次不再出现的旧候选：**已完成的保留**，仅清除未完成的过期候选；
- 全局限流只处理 `status NOT IN ('done','completed')`；
- 验证：标记 done 后重复 `generate`，该任务仍 `done`（三套测试均覆盖）。

## 9. 明日 3 件事生成链路
`submit_daily_review`：汇总当日 `get_today_tasks` 的完成/未完成 → 未完成按「优先级 → 红标 → id」取前 3 作 `tomorrow_actions`，并落 `daily_review`。
因桥接后任务非空 → 完成任务可提交复盘 → **`tomorrow_actions` 非空**（闸门4 实测 2 条）。

## 10. DB 迁移：force_p0 兼容旧库
- `SCHEMA` 的 `store_action_task` 增加 `force_p0 INTEGER NOT NULL DEFAULT 0`（新库直接带）；
- `init_db` 新增 `_migrate_task_columns`：`PRAGMA table_info` 检测，缺列则 `ALTER TABLE store_action_task ADD COLUMN force_p0 INTEGER NOT NULL DEFAULT 0`；
- 仅作用于**独立测试 SQLite**（`STORE_MANAGER_V013_DB_PATH`），不动主库/生产库；旧任务 `force_p0` 默认 0（行为安全）。

## 11. 风险点与回滚
**风险点**
1. 诊断/聚合多次调用时的优先级重算 —— 已做幂等（保留 done、按基准重算），重复调用结果稳定；
2. 当顾客紧急项（投诉/红警）多时，诊断 P0 可能被降为 P1（紧急客户事项优先占用 P0 名额）—— 设计如此，诊断任务仍以 P1 可见，today-tasks 不为空；
3. `force_p0` 旧库迁移 —— 仅 ALTER 加列，默认 0，不改既有数据语义。

**回滚**
- 纯后端改动，`git revert 5484630` 即回到 `2949888`；
- `force_p0` 列残留无害（默认 0，旧逻辑不读即不受影响）；独立测试库，不涉及主库/生产迁移回滚。

## 12. 测试结论
- isolated smoke：**39 PASS / 0 FAIL**
- app-level smoke：**10 PASS / 0 FAIL**
- four_gate_check_v013.py：**18 PASS / 0 FAIL（100%）**
- 关键验证：诊断生成 action_task ✅ / today-tasks>0 ✅ / 两类聚合 ✅ / P0≤3 ✅ / 投诉 force_p0 永远P0 ✅ / done 后重复 generate 不丢状态 ✅ / tomorrow_actions 非空 ✅

## 13. 边界声明
仅后端代码 + 测试脚本。未 push / 未 merge / 未部署 / 未 scp / 未热修 ECS / 未改测试库 / 未改 Nginx / 未改安全组 / 未开放公网 / 未动 18080 / 未动生产库 / 未动前端 / 未进 Qoder。
