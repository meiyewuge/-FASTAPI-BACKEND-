# 店长工作台 V0.1.3 · 后端开发交付报告（第一阶段）

> 仓库：`-FASTAPI-BACKEND-` ｜ 分支：`store-manager-v0.1.3-backend`（基于 `68263a1`）
> 范围：**仅后端**。不做前端、不做 UI、不动 MWUZS-MINIAPP。
> 状态：**未 push、未 merge、未部署、未动 18080、未动生产库/V0.1.1。** 全部本地 commit。
> 优先级原则：总审补丁说明 V0.1 最高，冲突以补丁说明为准（8 个补丁已全部纳入）。

---

## 1. git log --oneline（68263a1..HEAD）

```
5841e7c test(v0.1.3-M7): 后端smoke_test覆盖全端点+第四闸门11步(24/24通过)
c713287 feat(v0.1.3-M6): 诊断编排 + Schemas + API路由(/api/store-manager)
2728a4e feat(v0.1.3-M5): 今日任务P0限流 + 复盘闭环(补丁2)
2ee624b feat(v0.1.3-M4): 顾客经营模型(档案/项目/家居/需求/红黄预警/看板)
9f1994b feat(v0.1.3-M3): 9类诊断规则引擎 + StoreBenchmarkConfig + library_ref静态映射
e5f9cde feat(v0.1.3-M2): 13个自动计算指标(除零安全,率字段只读)
78c853b feat(v0.1.3-M1): 数据底座 14 张表 + 高频索引(独立SQLite,不动主库)
4ef0c32 chore(v0.1.3): 落位 5 份 V0.1.3 文档
```

## 2. git diff 摘要（68263a1..HEAD）

```
16 files changed, 1829 insertions(+)
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
docs/v0.1.3/*.docx (5 份文档)
```

## 3. 改动文件清单

**新增代码（全部在 `backend/app/store_manager/` 独立子包内）：**
| 文件 | 职责 | 对应模块 |
|------|------|----------|
| `db_v013.py` | 14 张表 DDL + 索引（独立 SQLite） | M1 |
| `metrics_v013.py` | 13 自动计算指标（除零安全） | M2 |
| `diagnosis_v013.py` | 9 类诊断规则 + 阈值配置 + 文案边界 | M3 |
| `library_ref.py` | 7 大库静态映射 | M3 |
| `customer_ops_v013.py` | 顾客/项目/家居/需求/预警/看板 | M4 |
| `tasks_v013.py` | 今日任务 P0 限流 + 复盘闭环 | M5 |
| `pipeline_v013.py` | 诊断编排（原始→指标→诊断→落库） | M6 |
| `schemas_v013.py` | pydantic 请求模型 | M6 |
| `router_v013.py` | `/api/store-manager` 路由 | M6 |
| `backend/smoke_test_v013.py` | 后端 smoke + 第四闸门 | M7 |

**修改现有：**
- `backend/app/main.py`：**仅新增 2 行**注册 `store_manager_v013_router`。未改任何现有 router/接口。

## 4. 新增数据表清单（14 张，独立 SQLite，不入主库）

`store_daily_raw_data`(15项原始) · `store_computed_metrics`(13指标) · `store_diagnosis_result` · `store_diagnosis_issue` · `store_action_task`(任务+限流字段) · `customer_profile`(RFM) · `customer_project` · `customer_home_product` · `customer_demand` · `customer_warning` · `customer_follow_task` · `daily_demand_board` · `daily_review` · `store_benchmark_config`(补丁1)

索引：基础索引 + 补丁5 的 6 个高频复合索引（共 30 个）。

## 5. API 清单（前缀 `/api/store-manager`，补丁4 不启 v2）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/daily-raw-data` | 录入 15 项原始数据 |
| GET | `/computed-metrics` | 13 自动计算指标 |
| POST | `/monthly-diagnoses` | 生成诊断（原始→指标→9规则→top3） |
| GET | `/diagnosis/{id}` | 取诊断报告 |
| GET/PUT | `/benchmark-config` | 健康线阈值配置（补丁1） |
| GET | `/today-tasks` | 今日任务（含 `generate` 参数） |
| POST | `/today-tasks/generate` | 生成今日任务（P0 限流） |
| PUT | `/tasks/{id}/status` | 更新任务状态 |
| POST | `/daily-review` | 提交复盘（返回明日 3 件事） |
| GET | `/daily-review/history` | 复盘历史 |
| POST/GET | `/customers` `/customers/{id}` | 顾客档案 |
| POST | `/customers/{id}/projects` | 在店项目 |
| POST | `/customers/{id}/projects/{pid}/consume` | 项目消耗（触发预警） |
| POST | `/customers/{id}/home-products` | 家居产品 |
| POST/PUT | `/customers/{id}/demands` `/demands/{did}` | 需求管理 |
| GET | `/warnings` | 预警清单 |
| GET | `/demand-board` | 今日需求看板 |

响应统一 `{code:1000, msg, data, api_version:"v0.1.3"}`。

## 6. smoke_test 结果

`python backend/smoke_test_v013.py` → **24 PASS / 0 FAIL**。
- 基础端点：health / daily-raw-data / monthly-diagnosis / computed-metrics(13项,除零安全) / benchmark-config(GET默认+PUT) / 诊断文案边界(规则诊断,非"AI智能") ✅
- 第四闸门顾客经营全链路 11 步：建档(phone唯一)→项目→消耗→消耗至0触红警→家居→需求→进度≥8进可成交💰→看板→生成任务→改状态→复盘含 tomorrow_actions ✅
- 零容忍项（5xx/traceback/写失败/除零）：无 ✅
- 模块级自测：M1 表14/14 · M2 指标对齐文档样例 · M3 规则top3 · M4 预警去重 · M5 P0限流(投诉永远P0/降级保留🔥/合并) 全通过。

> 说明：因当前环境未装 weasyprint（系统库），未做"整库一次性启动"冒烟；store-manager 与 weasyprint 无依赖，已用隔离挂载完整验证。整库启动冒烟留待部署前环境（扣子）执行。

## 7. 未完成 / 待确认问题清单

1. **部分规则阈值未配置化**：客流(daily_visits<20)、新客承接(new_conversion<50%)、锁客(recharge<30%)、项目结构(main_project_ratio<50%) 用的是规则级默认常量（文档表格中该列为图片/未给精确数值）。成交/复购/人效/客单/服务风险已接 `StoreBenchmarkConfig`。→ 待吴哥确认这 4 个阈值的精确值，可后续并入 benchmark 配置。
2. **客单/人效规则需目标值才触发**：`avg_order_target`/`per_capita_target` 默认 0 时不触发（避免误报）。→ 联调时需为门店设置目标值。
3. **`generate_today_tasks` 重复调用会重建当日任务**（清旧重建 customer_ops 来源任务，会重置状态）。正常流程每日生成一次；如需"增量保留状态"需再设计。
4. **severity 取规则内代表值**（区间如 7-9 取固定值），未做按偏离度动态打分。
5. **第四闸门 smoke 为隔离挂载**，整库启动冒烟待部署前环境执行（见第 6 节）。
6. **04_总审证据包** 本次未提供，当前以 5 份文档为准。

## 8. 边界声明（本阶段严格遵守）

- ❌ 未 push（本地 commit，分支无 upstream）
- ❌ 未 merge
- ❌ 未部署 ECS、未 scp
- ❌ 未动 18080 测试服务、未改 Nginx
- ❌ 未动 V0.1.1、未动生产数据库、未执行任何迁移
- ❌ 未改 MWUZS-MINIAPP 小程序仓库（仅后端）
- ✅ 仅 `-FASTAPI-BACKEND-` 后端、独立 SQLite、独立子包、main.py 仅 2 行注册
- ✅ 8 个总审补丁全部纳入；文案边界统一"规则诊断"，不接大模型

---

_本报告为 V0.1.3 后端第一阶段交付，待吴哥 + ChatGPT 审核。后续前端、联调、部署均为独立阶段。_
