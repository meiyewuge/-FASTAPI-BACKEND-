# 店长工作台 V0.1.3 · 后端代码审查包

> 用途：交扣子 / Codex / ChatGPT 做代码审查。**本阶段不部署、不 push、不 merge。**
> 仓库：`-FASTAPI-BACKEND-` ｜ 仅后端，未动 MWUZS-MINIAPP。

---

## 1. 基础 commit
`68263a1`（V0.1.2 P2 复审检查点补充，V0.1.3 分支由此切出）

## 2. 当前分支
`store-manager-v0.1.3-backend`（无 upstream，远程不存在 → 未 push）

## 3. HEAD / 提交口径（统一基准，三处一致）
| 角色 | commit | 说明 |
|------|--------|------|
| 基础 commit | `68263a1` | V0.1.3 分支切出点 |
| 首轮初审修订代码 HEAD | `f1f29a4` | 修复初审 3P0+3P1 |
| **代码 HEAD（本次复审对象）** | **`2949888`** | **最后一个含代码改动的提交**（阈值小提交 4 项：阈值配置化/幂等/时区/store_id校验） |
| 审查包同步提交（docs-only） | 其后提交 | 仅 `docs/v0.1.3/`，**无代码改动** |
> 阈值小提交详见 `STORE_MANAGER_V0_1_3_BACKEND_THRESHOLD_FIX_NOTES.md`；isolated smoke 35/0 + app 级 9/0。
> **口径定死**：① 代码修复 HEAD = `f1f29a4`（审查只到此为止的代码）；② 审查包为 docs-only 提交，`f1f29a4` 之后不改业务代码；③ `GIT_LOG.txt` 已逐行 `[CODE]/[DOCS]` 标注，`f1f29a4` 标为 ★代码修复HEAD。
> 三处（GIT_LOG / README / 本包）口径完全一致。

## 3.1 初审修订记录（ChatGPT 初审 3P0 + 3P1，已小修）
| 编号 | 问题 | 处理 |
|------|------|------|
| P0-1 | `/api/store-manager` 4 端点被 V0.1.2 老 router 屏蔽 | `main.py` 将 `router_v013` 提前注册→V0.1.3 生效；新增 `smoke_app_level_v013.py` 完整 app 级 smoke（9/0）验证；老 router 独有端点仍可达 |
| P0-2 | 默认 DB 可能落到生产目录 | 改用 `STORE_MANAGER_V013_DB_PATH`，默认 `/opt/meiye-wuyou-test/data/store_manager_workbench_v013.db`；写生产目录 fail-fast |
| P0-3 | 审查包 HEAD 不一致 | 本节明确区分 3 个 HEAD + docs 同步提交 |
| P1-4 | `metrics_id` 写成 None | `pipeline_v013` 保存 metrics 后写入 `metrics_id` |
| P1-5 | consume/demand 未校验归属 | router 校验 project/demand 属于 URL 的 `customer_id`，否则 404 |
| P1-6 | 优先级数字与文档不一致 | 统一 `P0=0/P1=1/P2=2/P3=3`（含诊断问题与任务 label） |

## 4. 本轮全部提交（git log --oneline，68263a1..HEAD）
```
86d64d3 docs(v0.1.3): 后端开发第一阶段交付报告(本地,不push)
5841e7c test(v0.1.3-M7): 后端smoke_test覆盖全端点+第四闸门11步(24/24通过)
c713287 feat(v0.1.3-M6): 诊断编排 + Schemas + API路由(/api/store-manager)
2728a4e feat(v0.1.3-M5): 今日任务P0限流 + 复盘闭环(补丁2)
2ee624b feat(v0.1.3-M4): 顾客经营模型(档案/项目/家居/需求/红黄预警/看板)
9f1994b feat(v0.1.3-M3): 9类诊断规则引擎 + StoreBenchmarkConfig + library_ref静态映射
e5f9cde feat(v0.1.3-M2): 13个自动计算指标(除零安全,率字段只读)
78c853b feat(v0.1.3-M1): 数据底座 14 张表 + 高频索引(独立SQLite,不动主库)
4ef0c32 chore(v0.1.3): 落位 5 份 V0.1.3 文档到 docs/v0.1.3/
```

## 5. git diff --stat（68263a1..HEAD）
```
17 files changed, 1951 insertions(+)
backend/app/main.py                              |   2 +
backend/app/store_manager/db_v013.py             | 349 +
backend/app/store_manager/customer_ops_v013.py   | 290 +
backend/app/store_manager/router_v013.py         | 247 +
backend/app/store_manager/tasks_v013.py          | 209 +
backend/app/store_manager/diagnosis_v013.py      | 207 +
backend/smoke_test_v013.py                       | 153 +
backend/app/store_manager/pipeline_v013.py       | 130 +
backend/app/store_manager/schemas_v013.py        | 102 +
backend/app/store_manager/library_ref.py         |  75 +
backend/app/store_manager/metrics_v013.py        |  65 +
docs/v0.1.3/*.docx (5 份) + 交付报告.md (122 +)
```

## 6. 本轮新增/修改文件清单
**修改（1）**：`backend/app/main.py`（仅 +2 行：import + include_router）。
**新增代码（11）**：`db_v013.py` / `metrics_v013.py` / `diagnosis_v013.py` / `library_ref.py` / `customer_ops_v013.py` / `tasks_v013.py` / `pipeline_v013.py` / `schemas_v013.py` / `router_v013.py`（均在 `backend/app/store_manager/`）+ `backend/smoke_test_v013.py`。
**新增文档**：`docs/v0.1.3/` 下 5 份 docx + 交付报告 + 本审查包。
> 现有 router（diagnoses/monthly/admin/weapp）、models、database、schemas、V0.1.2 子包文件：**零改动**。

## 7. 新增 14 张 SQLite 表（独立库，不入主库）
| # | 表 | 用途 |
|---|----|----|
| 1 | store_daily_raw_data | 15 项每日原始经营数据 |
| 2 | store_computed_metrics | 13 项自动计算指标 |
| 3 | store_diagnosis_result | 诊断报告主表（10 段） |
| 4 | store_diagnosis_issue | 诊断问题（含 severity/library_ref） |
| 5 | store_action_task | 今日任务（含限流字段 is_throttled_to_p1/keep_red_tag/merged_warning_count） |
| 6 | customer_profile | 顾客档案（RFM 自动） |
| 7 | customer_project | 在店项目（消耗/剩余） |
| 8 | customer_home_product | 家居产品（用完预警） |
| 9 | customer_demand | 需求管理（progress_score） |
| 10 | customer_warning | 红黄预警 |
| 11 | customer_follow_task | 顾客跟进任务 |
| 12 | daily_demand_board | 今日需求看板快照 |
| 13 | daily_review | 每日复盘（含 tomorrow_actions） |
| 14 | store_benchmark_config | 门店健康线阈值（补丁1） |

索引：基础索引 + 补丁5 的 6 个高频复合索引（合计约 30 个，全部 `IF NOT EXISTS`）。

## 8. 21 个 /api/store-manager 端点
```
POST  /daily-raw-data
GET   /computed-metrics
POST  /monthly-diagnoses
GET   /diagnosis/{diagnosis_id}
GET   /benchmark-config
PUT   /benchmark-config
GET   /today-tasks
POST  /today-tasks/generate
PUT   /tasks/{task_id}/status
POST  /daily-review
GET   /daily-review/history
POST  /customers
GET   /customers
GET   /customers/{customer_id}
POST  /customers/{customer_id}/projects
POST  /customers/{customer_id}/projects/{project_id}/consume
POST  /customers/{customer_id}/home-products
POST  /customers/{customer_id}/demands
PUT   /customers/{customer_id}/demands/{demand_id}
GET   /warnings
GET   /demand-board
```
响应统一：`{code:1000, msg:"success", data:..., api_version:"v0.1.3"}`。

## 9. 13 个自动计算指标（除零安全：分母为 0 一律置 0）
| 指标 | 公式 |
|------|------|
| conversion_rate | 成交客数 / 客流 ×100 |
| new_customer_ratio | 新客数 / 客流 ×100 |
| new_conversion_rate | 新客成交 / 新客数 ×100 |
| avg_order_value | 营收 / 成交客数 |
| appointment_arrival_rate | 到店 / 有效预约 ×100 |
| per_capita_efficiency | 营收 / 员工数 |
| recharge_ratio | 充值额 / 营收 ×100 |
| project_ratio | 项目业绩 / 营收 ×100 |
| product_ratio | 产品零售 / 营收 ×100 |
| main_project_ratio | 主推项目 / 项目业绩 ×100 |
| complaint_risk_index | 投诉 ×100 / 服务人次 |
| estimated_return_customers | 客流 − 新客（保守不为负） |
| service_efficiency | 服务人次 / 员工数 |
> 全部"率"仅由系统计算，不接受前端填写。

## 10. 9 类诊断规则（severity 降序取 top3）
| # | 问题类型(key) | 触发条件 | severity | 阈值来源 |
|---|---------------|----------|----------|----------|
| 1 | 客流 traffic | daily_visits < 20 | 8 | 规则默认（待配置化） |
| 2 | 成交 deal | conversion_rate < conversion_rate_green(60) | 8 | **StoreBenchmarkConfig** |
| 3 | 新客承接 new_customer | new_conversion_rate < 50% | 7 | 规则默认（待配置化） |
| 4 | 客单 price | avg_order_value < avg_order_target（>0 才判） | 7 | **StoreBenchmarkConfig** |
| 5 | 锁客 lock | recharge_ratio < 30% | 6 | 规则默认（待配置化） |
| 6 | 复购 repeat | 复购客占比 < return_customer_ratio_green_low(70) | 7 | **StoreBenchmarkConfig** |
| 7 | 项目结构 project | main_project_ratio < 50% | 6 | 规则默认（待配置化） |
| 8 | 员工人效 staff | per_capita_efficiency < per_capita_target（>0 才判） | 6 | **StoreBenchmarkConfig** |
| 9 | 服务风险 risk | complaint_risk_index > 3 或 有投诉 | 8/9 | 固定规则 |
> 每问题挂 7 大库 `library_ref` 静态映射（V0.1.4 换 RAG）。文案统一"规则诊断"，禁"AI 智能诊断"，附"AI深度分析将在V0.1.4接入"。

## 11. StoreBenchmarkConfig 默认阈值（补丁1）
首次读取/启动自动插入 `default_store` 默认配置；诊断规则从此读取，无配置 fallback 到 DEFAULT。
```
conversion_rate_green=60 · repurchase_rate_green=50 · appointment_arrival_rate_green=80
new_customer_ratio: 15~30 · return_customer_ratio: 70~85 · complaint_risk_max=5
monthly_target / avg_order_target / per_capita_target 默认 0（需门店设置后参与判定）
```
提供 GET/PUT `/benchmark-config`，V0.1.3 默认值即生效、可调。

## 12. P0 限流规则（补丁2）
1. 每天 P0 默认最多 3 条；
2. 投诉/退款/差评永远 P0（不受限流）；
3. 同一顾客多个预警合并为 1 张任务卡（标题"{顾客} 有N项紧急事项需处理"）；
4. P0 超 3 条时按「金额风险 > 顾客价值(RFM) > 时效性」排序；
5. 未入选红色项降为 P1，但保留红色标签（keep_red_tag=🔥）+ 防饥饿提示"今日 N 项 P0 候选因限流降为 P1，建议明天优先处理"。

## 13. 第四闸门 11 步后端链路（补丁3）
```
1 POST /customers (phone 唯一)
2 POST /customers/{id}/projects
3 POST /customers/{id}/projects/{pid}/consume (remaining-1)
4 消耗至 0 → customer_warning 生成 red
5 POST /customers/{id}/home-products
6 POST /customers/{id}/demands
7 PUT  /customers/{id}/demands/{did} progress≥8 → 看板标 💰
8 GET  /demand-board 正确聚合
9 today-tasks/generate 预警触发生成 store_action_task
10 PUT /tasks/{id}/status → POST /daily-review
11 复盘返回含 tomorrow_actions
```

## 14. smoke_test 完整输出（24 PASS / 0 FAIL）
```
=== 基础端点 ===
  [PASS] health
  [PASS] daily-raw-data — 200
  [PASS] monthly-diagnosis — 200
  [PASS] 诊断含 top3 + 规则文案(非AI智能)
  [PASS] get diagnosis
  [PASS] computed-metrics 13项
  [PASS] 除零安全(指标均数值)
  [PASS] benchmark-config GET 默认值
  [PASS] benchmark-config PUT
=== 第四闸门：顾客经营全链路 11 步 ===
  [PASS] G1 POST /customers 201/200 + phone唯一
  [PASS] G1 phone唯一约束生效(400) — 400
  [PASS] G2 POST projects
  [PASS] G3 consume remaining-1
  [PASS] G4 消耗至0生成red预警
  [PASS] G5 POST home-products
  [PASS] G6 POST demands
  [PASS] G7+G8 demand-board 可成交标💰
  [PASS] G9 预警触发生成 store_action_task
  [PASS] G10 PUT task status
  [PASS] G11 复盘返回 tomorrow_actions
  [PASS] today-tasks GET
  [PASS] daily-review/history
  [PASS] customers list
  [PASS] customer detail

=== smoke 结果：24 PASS / 0 FAIL ===
exit=0
```

## 14.1 app 级 smoke（修复 P0-1 后新增，9 PASS / 0 FAIL）
导入**真实 `app.main`**（无 weasyprint 时自动 stub），验证路由冲突已解决：
- 4 个原冲突端点（monthly-diagnoses[POST] / today-tasks[GET] / today-tasks/generate[POST] / tasks/{id}/status[PUT]）现响应 `api_version=v0.1.3`（V0.1.3 生效）✅
- V0.1.2 老 router 独有端点（/history、/monthly-diagnoses/{id}）仍可达 ✅
- V0.1.3 专属端点（benchmark-config、demand-board）可达 ✅
> isolated router smoke 因新增归属/优先级校验，由 24 → **27 PASS / 0 FAIL**。

## 15. 是否有 5xx / traceback / 异常日志
**无。** 两个 smoke（isolated 27/0 + app 级 9/0）全程无 5xx、无 traceback、无异常日志；零容忍项（5xx / traceback / 写入失败 / 除零）全部通过。
> app 级 smoke 已覆盖"整库 main.py 启动 + 路由不冲突"；weasyprint 在无系统库时用 stub（仅 smoke），真实 PDF 渲染依赖留待部署前环境。

## 16. 未完成 / 待确认问题清单
**16.1 待确认业务参数清单（4 个规则阈值）**
文档表格未给精确数值，当前用规则默认常量。吴哥已建议先按下表暂定，但**要求写入 `StoreBenchmarkConfig`、不写死在规则里**；代码审查通过后再统一补一个小提交：
| 规则 | 当前代码默认 | 吴哥暂定值 | 落位 |
|------|------|----------|------|
| 客流 traffic | daily_visits<20 | daily_visits<20 且 new_customer_ratio<15% | 待入 StoreBenchmarkConfig |
| 新客承接 new_customer | new_conversion_rate<50% | new_conversion_rate<40% | 待入 StoreBenchmarkConfig |
| 锁客 lock | recharge_ratio<30% | recharge_ratio<20% | 待入 StoreBenchmarkConfig |
| 项目结构 project | main_project_ratio<50% | main_project_ratio<40% | 待入 StoreBenchmarkConfig |
> 处理方式（已与吴哥确认）：**本审查阶段不改代码**，仅记录；审查通过后再以一个小提交统一把这 4 个阈值配置化并写入 benchmark 默认值。

**16.2 其他**
1. 客单/人效规则需门店设置目标值（avg_order_target/per_capita_target>0）才触发，否则不判（避免误报）。
2. `generate_today_tasks` 重复调用会重建当日 customer_ops 来源任务（重置状态）；正常每日生成一次。如需增量保留状态需再设计。
3. severity 取规则区间内代表值，未按偏离度动态打分。
4. 04_总审证据包本次未提供，当前以 5 份文档为准。

## 17. 红线自查
| 项 | 状态 |
|----|------|
| 未 push | ✅（分支无 upstream，远程不存在） |
| 未 merge | ✅ |
| 未部署 ECS | ✅ |
| 未 scp | ✅ |
| 未动 18080 测试服务 | ✅ |
| 未动 V0.1.1 主链路 | ✅（现有 router/模型零改动） |
| 未动生产数据库 / 未迁移 | ✅（独立 SQLite，不入主库） |
| 未改 Nginx | ✅ |
| 未动 MWUZS-MINIAPP | ✅（该仓库工作区干净，本轮零提交；+2059 为 V0.1.2 旧 PR 累计差异） |

## 18. 建议下一步
1. 将本审查包交 **扣子 / Codex / ChatGPT** 做代码审查（架构、SQL 注入面、并发、错误处理、字段一致性、限流正确性）。
2. **不进入部署**。审查通过后，再：① 统一补 4 个阈值配置化小提交；② 评估部署到 ECS **18081**（V0.1.3 测试端口，与 18080 V0.1.2 隔离）；③ 整库启动冒烟（含 weasyprint）。
3. 顺序：生成审查包 → 扣子收包 → Codex/ChatGPT 审查 → 通过 → 补阈值小提交 → 再部署 18081。

---

_生成后停住，等待吴哥安排扣子工具链审查。本阶段不 push、不部署。_
