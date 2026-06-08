# 店长工作台 V0.1.2 · P2 后端修复报告

> 文件：`STORE_MANAGER_V0_1_2_P2_BACKEND_FIX_REPORT.md`
> 仓库：`-FASTAPI-BACKEND-`
> 分支：`claude/quirky-turing-wHaIa`
> 级别：P2
> 状态：**已修复并自测通过。未部署、未 merge、未上线、未改主库、未动 V0.1.1。**

---

## 1. 问题描述

`GET /api/store-manager/today-tasks` 接收 `date` 参数，但后端实际**未按 date 过滤**：`storage.list_tasks()` 只按 `store_id` 查最近 50 条任务并丢弃了 `date`。

**后果**：店长多次生成报告后，不同日期生成的任务都堆在同一 `store_id` 下，"今日优先级清单"会**混入历史任务**，无法只看当天。

---

## 2. 根因

- `router.py` 的 `get_today_tasks(store_id, date="")` 收到了 `date`，但调用时写的是 `storage.list_tasks(store_id)`，**未把 date 传下去**。
- `storage.list_tasks(store_id)` 只有 `WHERE store_id = ? ORDER BY created_at DESC LIMIT 50`，**无日期维度**；且 `store_manager_tasks` 表**没有日期列**可供过滤。

---

## 3. 修复方案

给任务增加"所属日期"维度，并按 `store_id + date` 过滤。

- 新增列 `task_date TEXT`（值为 **报告生成日 YYYY-MM-DD**）。
- 写入时记录 `task_date`；查询时按 `store_id + date` 过滤；`date` 缺省取**今天**。
- 对已存在但缺列的旧库做安全 `ALTER TABLE ADD COLUMN`（独立 SQLite，无主库影响）。

---

## 4. 修改文件（仅 store_manager 子包 2 个文件）

### 4.1 `backend/app/store_manager/storage.py`

1. **`init_db`**：`store_manager_tasks` 建表新增 `task_date TEXT`；对旧库 `PRAGMA table_info` 检测后安全 `ALTER ... ADD COLUMN task_date`；新增索引 `idx_store_manager_tasks_store_date (store_id, task_date)`。
2. **`save_report`**：计算 `task_date = report.generated_at[:10]`（缺省取今天），写入任务行。
3. **`list_tasks(store_id, date="")`**：签名新增 `date`；`target_date = date[:10] or 今天`；查询改为 `WHERE store_id = ? AND task_date = ?`。

### 4.2 `backend/app/store_manager/router.py`

- `get_today_tasks`：`storage.list_tasks(store_id)` → **`storage.list_tasks(store_id, date)`**（把 date 传给 storage）。

> 未改 `engine.py` / `schemas.py` / `__init__.py` / `main.py`，未改任何其它 router。

---

## 5. 接口自测结果

环境：`TestClient` 挂载 `store_manager_router`，独立临时 SQLite。先用 storage 落一条"昨天(2026-06-06)"的历史任务，再通过接口生成"今天(2026-06-08)"的报告，模拟"多次生成报告"的场景。

**结果：6 / 6 全通过。**

| 用例 | 结果 |
|------|------|
| 库中同时存在多日期任务（昨天 + 今天，共 3 条） | ✅ |
| `GET .../today-tasks?store_id=s1&date=<今天>` 只返回当天任务 | ✅ |
| 今日清单**不含**历史任务 `task_old_1` | ✅ |
| `?date=<昨天>` 只返回昨天那条 | ✅ |
| `date` 缺省 → 默认取今天（等价于 `?date=<今天>`） | ✅ |
| `?date=<无任务日期>` → 返回空 | ✅ |

**核心验证（满足验收要求）**：
```
GET /api/store-manager/today-tasks?store_id=xxx&date=YYYY-MM-DD
→ 只返回该 store_id 在该 date 当天生成的任务，历史任务不再混入。
```

补充：`py_compile` 语法检查通过。

---

## 6. 边界确认

- ✅ router.py 已接收 `date` 参数
- ✅ router.py 已把 `date` 传给 storage
- ✅ storage 查询 today_tasks 按 `store_id + date` 过滤
- ✅ 不再只按 `store_id` 查最近 50 条
- ✅ 不改主库（仅独立 SQLite 加列，旧库安全 ALTER）
- ✅ 不改 V0.1.1 诊断链路
- ✅ 不改 diagnoses / monthly / weapp / admin 等原有 router
- ✅ 不部署 / 不 merge / 不上线

---

## 7. 兼容性与回滚

- **兼容性**：新列 `task_date` 对旧库自动 `ALTER` 补齐；老数据 `task_date` 为 `NULL`，按日期查询不会命中（即旧任务不会再混入今日清单，符合预期）。如需让某条旧任务出现在指定日期，可单独补值。
- **回滚**：本次仅改 store_manager 子包 2 文件，`git revert` 本次 commit 即可；独立 SQLite 加列不影响主库；无主库迁移回滚。

---

## 8. 复审检查点确认（按复审要求补充）

### 8.1 `task_date` 的日期口径
- 后端 `task_date` 按 **报告生成日 `YYYY-MM-DD`** 存储，取自 `report.generated_at[:10]`（缺省回退当天）。
- 前端 `getTodayTasks` 传入的是 `new Date().toISOString().slice(0,10)`（也是 `YYYY-MM-DD`）。
- 两边都是日期（年月日，无时分秒、无时区偏移参与比较），格式一致。
- ⚠️ **联调时需确认时区口径**：后端 `task_date` 取自服务器本地时间（`datetime.now()`），前端 `toISOString()` 为 **UTC**。若服务器时区非 UTC（如 UTC+8），跨零点时段可能出现"前端按 UTC 日期、后端按本地日期"差一天的边界情况。**联调首轮需校验：同一次生成的报告，前端用 `toISOString` 切出的 date 能命中后端的 `task_date`。** 如不一致，建议统一为同一时区口径（推荐都用门店本地日期）。

### 8.2 旧库兼容（`task_date = NULL`）
- 对已存在但缺列的旧库，`init_db` 通过 `PRAGMA table_info` 检测后安全 `ALTER TABLE ADD COLUMN task_date`，不会丢数据。
- 旧任务的 `task_date` 为 `NULL`，按日期查询（`WHERE task_date = ?`）**不会命中**，因此**旧任务不会再混入任何一天的今日清单** —— 这正是本次修复想要的行为，明确记录在案。
- 如确需让某条历史旧任务出现在指定日期，可单独为其补写 `task_date`（本期不做）。

---

## 9. 当前阶段定盘

```text
P2 后端修复：完成，自测 6/6 通过
后端 PR：仍为同一分支 claude/quirky-turing-wHaIa（本次为新增 commit）
merge：未做
部署：未做
上线：未做
```

> 本修复推送到既有分支，进入同一后端 PR。是否合并/联调仍按既定流程：等微信开发者工具点测 + 审核 + 吴哥拍板。
