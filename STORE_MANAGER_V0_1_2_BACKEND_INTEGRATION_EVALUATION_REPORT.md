# 店长工作台 V0.1.2 · 后端接入评估报告

> 文件：`STORE_MANAGER_V0_1_2_BACKEND_INTEGRATION_EVALUATION_REPORT.md`
> 仓库：`-FASTAPI-BACKEND-`（后端服务）
> 分支：`claude/quirky-turing-wHaIa`
> 阶段：**第三步 · 后端接入评估（只评估，不施工）**
> 状态：**未改后端代码、未改数据库、未部署、未碰 V0.1.1 稳定版。本文件为纯文档（docs）。**

---

## 0. 评估方法与依据

- 只读现有 `-FASTAPI-BACKEND-/backend`，未修改任何后端文件。
- 对照代码包：`docs/API_CONTRACT.md`、`docs/BACKEND_INTEGRATION_GUIDE.md`、`backend_patch/fastapi/`。
- 额外验证：在代码包目录内**单独运行了规则引擎**（纯 stdlib，未触碰现有后端），`generate_report()` 正常产出 3 个核心问题、3 条今日任务、7 段展示文本，目标完成率计算正确（66.7%）。

---

## 1. 当前 FASTAPI-BACKEND 项目结构

```text
backend/
├── run.py                  # 启动入口：把 backend 加入 sys.path，uvicorn 运行 app.main:app
├── requirements.txt        # fastapi 0.115 / SQLAlchemy 2.0 / pydantic 2.10 / psycopg2 / weasyprint 等
└── app/
    ├── __init__.py
    ├── main.py             # FastAPI 实例 + CORS + 注册 4 个 router + 挂载 /reports
    ├── config.py           # pydantic-settings；database_url 默认 sqlite:///./storecoach.db
    ├── database.py         # SQLAlchemy engine / SessionLocal / Base / get_db
    ├── models.py           # ORM：Store / Diagnosis / MonthlyCheckup 等
    ├── schemas.py          # 【单文件】Pydantic 模型（非目录）
    ├── scoring.py          # V0.1.1 评分逻辑
    ├── mba_models.py       # V0.1.1 分析
    ├── ai.py               # LLM 调用
    ├── report.py           # PDF 渲染
    ├── routers/            # diagnoses / monthly / admin / weapp
    └── templates/          # 报告 HTML 模板
```

- 数据持久层：**SQLAlchemy**，`Base.metadata.create_all(bind=engine)` 在启动时建表。
- **无 `app/services/` 目录**；**`schemas` 是单文件 `schemas.py`，不是包**。

---

## 2. app/main.py 当前 router 注册情况

```python
from .routers import diagnoses, monthly, admin, weapp   # 相对导入

app.include_router(diagnoses.router)          # prefix=/api/diagnoses
app.include_router(monthly.router)            # prefix=/api/monthly-checkups
app.include_router(admin.router)              # prefix=/api/admin
app.include_router(weapp.router, prefix="/api", tags=["weapp"])
app.mount("/reports", StaticFiles(...))
@app.get("/health")
```

> 注意：现有代码用**相对导入** `from .routers import ...`；代码包补丁用**绝对导入** `from app.routers... / app.schemas... / app.services...`。两者在 `run.py`（已把 backend 加入 sys.path）下均可运行，但风格不一致，接入时需统一。

---

## 3. 已有 routers / schemas / services / models

| 类别 | 现状 |
|------|------|
| routers | `diagnoses.py`、`monthly.py`、`admin.py`、`weapp.py` |
| schemas | 单文件 `app/schemas.py`（Pydantic v2） |
| services | **不存在**（无 `app/services/` 目录） |
| models | `app/models.py`：`Store`、`Diagnosis`、`MonthlyCheckup` 等（SQLAlchemy ORM） |
| 数据库 | SQLAlchemy；默认 `sqlite:///./storecoach.db`，已装 `psycopg2`（可切 Postgres） |

---

## 4. 是否已有类似 store_manager 的接口

**没有。** 现有路由前缀为 `/api/diagnoses`、`/api/monthly-checkups`、`/api/admin`、`/api/*`(weapp)。
**不存在任何 `/api/store-manager/*` 接口、不存在 `store_manager_*` 模型或表。** 完全是新增模块。

---

## 5. 需要新增哪些 router（1 个）

`app/routers/store_manager_workbench.py`（代码包已提供），`prefix=/api/store-manager`，含 8 个端点：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/store-manager/monthly-diagnoses` | 提交 15 项数据 → 生成报告 |
| GET | `/api/store-manager/monthly-diagnoses/{report_id}` | 取单份报告 |
| GET | `/api/store-manager/history?store_id=` | 历史报告列表 |
| POST | `/api/store-manager/today-tasks/generate` | 生成今日任务（≤5） |
| GET | `/api/store-manager/today-tasks?store_id=&date=` | 取今日任务 |
| PUT | `/api/store-manager/tasks/{task_id}/status` | 更新任务状态 |
| POST | `/api/store-manager/tasks/{task_id}/review` | 提交复盘 |
| POST | `/api/store-manager/admin/reports/{report_id}/mark` | 后台人工标记（前端 MVP 暂未调用） |

> 前 7 个与小程序 `utils/managerApi.js` 已对齐；第 8 个为后台标记，供管理端后续使用。

---

## 6. 需要新增哪些 schema（1 个文件）

代码包 `app/schemas/store_manager_workbench.py`，含：
`MonthlyDiagnosisRequest`、`CoreIssue`、`WeeklyAction`、`TodayTask`、`StaffSuggestion`、`StructuredReport`、`MonthlyDiagnosisResponse`、`GenerateTodayTasksRequest`、`UpdateTaskStatusRequest`、`TaskReviewRequest`、`AdminMarkRequest`。

> ⚠️ **结构冲突（重点）**：代码包把它放在 `app/schemas/`（**包/目录**），但现有项目 `app/schemas.py` 是**单文件**。同一包内 `schemas.py` 与 `schemas/` 目录**不能共存**。见第 13 节接入方案。

---

## 7. 需要新增哪些 service（2 个文件 + 1 个新目录）

- `app/services/store_manager_engine.py`：规则引擎 + 模板化文本生成（纯 stdlib，无外部依赖；已实跑验证通过）。
- `app/services/store_manager_storage.py`：持久层。
- 需**新建 `app/services/` 目录**（含 `__init__.py`）。该目录现不存在，纯新增、无冲突。

---

## 8. 是否需要数据库迁移

**MVP（SQLite）下不强制需要。** storage 用原生 `sqlite3`，每次连接调用 `init_db()` **自动建表**（`store_manager_reports`、`store_manager_tasks`），并自动建索引。
代码包另附 `migrations/store_manager_workbench.sql` 仅供参考 / 未来切 Postgres 时手动迁移。

> 关键：storage 写的是**独立 SQLite 文件**（`STORE_MANAGER_DB_PATH`，默认 `/opt/meiye-wuyou/data/store_manager_workbench.db`），**与现有 SQLAlchemy 主库（storecoach.db / Postgres）完全分离，不进主库、不碰 ORM 模型**。这满足"不改主库"边界，但也意味着工作台数据与主库是两套存储（见第 15 节风险）。

---

## 9. 当前数据库是 SQLite 还是其他

- 现有后端：**默认 SQLite**（`sqlite:///./storecoach.db`），通过 `DATABASE_URL` 可切 **Postgres**（`psycopg2` 已安装）。
- 工作台 storage：**固定原生 SQLite**（独立文件），不读 `DATABASE_URL`，当前不支持 Postgres。

---

## 10. 是否会影响现有 /api/diagnoses

**不会。** 新 router 前缀 `/api/store-manager`，与 `/api/diagnoses` 无任何路由重叠；不共享模型、不共享表、不改 `diagnoses.py`。

---

## 11. 是否会影响 /api/monthly-checkups

**不会。** 同上，前缀不同、代码独立。`monthly.py`、`scoring.py`、`mba_models.py` 均无需改动。

---

## 12. 是否会影响小程序已有接口

全部在 weapp.py 的 `/api/*` 下，与 `/api/store-manager/*` **无路径冲突**，均不受影响：

| 接口 | 影响 |
|------|------|
| `/api/auth/wechat-login` | 无 |
| `/api/stores/profile` | 无 |
| `/api/content/generate` | 无 |
| `/api/ai/chat` | 无 |
| `/api/coach/webview-token` | 无 |

> 唯一需改动的现有文件是 `app/main.py`（新增 2 行：import + include_router）。其余现有文件零改动。

---

## 13. 推荐接入方案

**目标：把代码包补丁接入，且不与现有 `schemas.py` 单文件冲突、不改 V0.1.1。**

**推荐（A 案 · 子包隔离，最稳）**：把工作台后端整体收敛到一个独立子包，避免与 `schemas.py` 冲突、降低耦合：

```text
app/store_manager/
├── __init__.py
├── router.py      ← 来自 store_manager_workbench.py
├── schemas.py     ← 来自 schemas/store_manager_workbench.py
├── engine.py      ← 来自 services/store_manager_engine.py
└── storage.py     ← 来自 services/store_manager_storage.py
```

并把补丁内的导入相应改为子包内相对/绝对导入。`main.py` 仅加：

```python
from app.store_manager.router import router as store_manager_router
app.include_router(store_manager_router)
```

- 优点：完全规避 `app/schemas.py` 与 `app/schemas/` 目录冲突；模块自洽、易回滚（删目录 + 删 2 行）。
- 代价：需调整补丁内 4 处 import 路径（机械改动，不改逻辑）。

**备选（B 案 · 按代码包原路径）**：新建 `app/services/`（无冲突），但 `schemas` 必须二选一：
- B1：把 schema 放成单文件 `app/schemas_store_manager.py`（不建 `schemas/` 目录），import 相应调整；
- B2：将现有 `app/schemas.py` 升级为 `app/schemas/` 包（`__init__.py` 再导出原内容）——**会触碰 V0.1.1 相关文件，不推荐**。

> 倾向 **A 案**：隔离度最高、对存量零侵入、回滚最干净。

**统一事项（无论 A/B）**：
1. import 风格与现有相对导入统一；
2. `req.dict()` 改为 pydantic v2 的 `req.model_dump()`（见第 15 节）；
3. 通过环境变量明确 `STORE_MANAGER_DB_PATH` 到可写、可备份目录。

---

## 14. 回滚方案

接入采用"纯新增 + main.py 两行"，回滚极简：

1. 注释 / 删除 `main.py` 中新增的 `import` 与 `include_router` 两行 → `/api/store-manager/*` 立即下线，其余服务不受影响；
2. 删除新增子包目录（A 案：`app/services/` + 子包文件，或 `app/store_manager/`）；
3. 工作台独立 SQLite 文件可保留或删除，**不影响主库**；
4. 因未改任何现有文件（除 main.py 两行）、未改主库 schema，**无数据迁移回滚**。

> 建议：接入走独立分支 + PR，先 `/health` 与 7 个端点冒烟通过再合并；保留合并前 commit 以便一键 revert。

---

## 15. 风险点

| # | 风险 | 等级 | 说明 / 缓解 |
|---|------|------|-------------|
| 1 | `schemas.py` 单文件 vs `schemas/` 目录冲突 | 中 | 按第 13 节 A 案子包隔离规避 |
| 2 | 双存储：工作台独立 SQLite，与主库分离 | 中 | 满足"不改主库"，但数据不在主库，需单独备份；若未来要统一报表/导出需再设计 |
| 3 | `STORE_MANAGER_DB_PATH` 路径不可写 | 中 | 部署前确认目录存在且可写、纳入备份；扣子部署时配置环境变量 |
| 4 | storage 不支持 Postgres（固定 sqlite3） | 低-中 | MVP 可接受；若主库为 Postgres 且要统一，需后续改造 storage |
| 5 | `req.dict()` 为 pydantic v2 已废弃用法 | 低 | 改 `model_dump()`，消除告警，避免未来版本不兼容 |
| 6 | store-manager 端点无鉴权（含 admin/mark） | 中 | 至少给 `/admin/*` 加 `x-admin-key`（复用现有 admin 依赖）；其余端点对齐 weapp 鉴权策略 |
| 7 | store_id 为自由字符串，与主库 Store(int id) 解耦 | 低 | MVP 可接受；联调时约定小程序传入的 store_id 口径 |
| 8 | import 风格不统一（绝对 vs 相对） | 低 | 接入时统一，避免 IDE/打包歧义 |
| 9 | 今日任务来源仅取报告内 today_tasks + manual | 低 | 与前端 MOCK 行为一致；符合"手动生成、不启 cron" |

---

## 16. 需要吴哥确认的问题

1. **接入方案**：采用推荐的 **A 案（`app/store_manager/` 子包隔离）**，还是 B1（services + 单文件 schema）？（我倾向 A 案）
2. **存储策略**：工作台是否就用**独立 SQLite 文件**（满足不改主库），还是未来要并入主库 / 走 Postgres？本期建议先独立 SQLite。
3. **鉴权要求**：`/api/store-manager/*` 是否需要登录态？`/admin/reports/{id}/mark` 是否加 `x-admin-key`？（建议至少保护 admin）
4. **store_id 口径**：小程序应传什么作为 `store_id`（openid？门店表 id？固定值）？需前后端对齐。
5. **DB 路径**：`STORE_MANAGER_DB_PATH` 在阿里云上的具体可写目录与备份策略由谁定（建议扣子部署时确认）。
6. **LLM**：本期引擎为规则 + 模板（不强依赖大模型），是否本期就接现有 LLM 网关做润色，还是留到下一版？（建议下一版）

---

## 17. 边界确认（本评估阶段）

- ✅ 未改后端代码（本文件为纯 docs）
- ✅ 未改数据库、未建表、未迁移
- ✅ 未部署、未启服务
- ✅ 未启 cron、未接企微
- ✅ 未自动写 memory_tree / Nyx / knowledge_workflow
- ✅ 未做美容师档口 / 老板档口 / 顾客档案 / 品相表
- ✅ 未触碰 V0.1.1 诊断稳定版（diagnoses / monthly / scoring / mba_models）

---

## 18. 结论与下一步

- 现有后端结构清晰，store-manager 模块为**纯新增**，与 V0.1.1 及所有现有接口**无路由 / 无模型 / 无主库冲突**；唯一需改的现有文件是 `main.py`（2 行）。
- 主要待决项是**结构落位方案（第 13 节）**与**6 个确认问题（第 16 节）**。
- **下一步建议**：吴哥就第 16 节拍板后，再进入"第四步：后端接入施工"（仍按分支 + PR，先冒烟、不直接部署）；扣子在确认后再于阿里云拉服务。

> 本阶段定为：**后端接入评估完成，等吴哥确认接入方案与待决问题。后端仍未施工、未部署。**
