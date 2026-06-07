# 店长工作台 V0.1.2 · 后端分支内施工交付报告

> 文件：`STORE_MANAGER_V0_1_2_BACKEND_BRANCH_DELIVERY_REPORT.md`
> 仓库：`-FASTAPI-BACKEND-`（后端服务）
> 分支：`claude/quirky-turing-wHaIa`
> 阶段：**第四步 · 后端分支内施工（仅分支，不部署、不上生产）**
> 状态：**未部署、未改主库、未动 V0.1.1 主链路。仅新增独立子包 + main.py 注册 2 行。**

---

## 0. 施工依据（吴哥拍板）

- 接入落位：**A 案**，独立子包 `app/store_manager/`，不新建 `app/schemas/` 目录（规避与现有 `app/schemas.py` 单文件冲突）。
- 存储策略：**独立 SQLite**，`STORE_MANAGER_DB_PATH=/opt/meiye-wuyou/data/store_manager_workbench.db`，不并入主库。
- main.py 仅新增 router 注册，不改任何现有接口。
- Pydantic：用 `model_to_dict()` 兼容 v1/v2，不只用 `req.dict()`。
- 后台保护：`/api/store-manager/admin/*` 加 `X-Admin-Key` 校验，环境变量 `STORE_MANAGER_ADMIN_KEY`。
- 本期不接大模型：规则引擎 + 模板输出。

---

## 1. 新增文件

独立子包 `backend/app/store_manager/`（6 个文件）：

| 文件 | 来源 / 说明 |
|------|-------------|
| `__init__.py` | 子包说明 + `model_to_dict()`（pydantic v1/v2 兼容函数） |
| `router.py` | 来自代码包 `routers/store_manager_workbench.py`，已适配：子包内相对导入、`model_to_dict()`、admin 鉴权 |
| `schemas.py` | 来自代码包 `schemas/store_manager_workbench.py`，原样 |
| `engine.py` | 来自代码包 `services/store_manager_engine.py`，原样（规则引擎 + 模板，纯 stdlib） |
| `storage.py` | 来自代码包 `services/store_manager_storage.py`，原样（独立 SQLite，自动建表） |

> 未新建 `app/schemas/` 目录、未新建 `app/services/` 目录 —— 全部收敛进 `app/store_manager/` 子包，对存量零侵入。
> `__pycache__/` 已被 `.gitignore` 忽略，未入库。

---

## 2. 修改文件

仅 `backend/app/main.py`，**新增 2 行**（相对导入，风格与现有 `from .routers import ...` 一致）：

```diff
 from .routers import diagnoses, monthly, admin, weapp
+from .store_manager.router import router as store_manager_router
 import os
@@
 app.include_router(weapp.router, prefix="/api", tags=["weapp"])
+app.include_router(store_manager_router)
```

> 现有 4 个 router 注册、`/reports` 挂载、`/health`、CORS 均未改动。

---

## 3. 接口清单（前缀 `/api/store-manager`）

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| POST | `/api/store-manager/monthly-diagnoses` | 无 | 提交 15 项数据 → 生成报告 |
| GET | `/api/store-manager/monthly-diagnoses/{report_id}` | 无 | 取单份报告（不存在→404） |
| GET | `/api/store-manager/history?store_id=` | 无 | 历史报告列表 |
| POST | `/api/store-manager/today-tasks/generate` | 无 | 生成今日任务（≤5，手动触发） |
| GET | `/api/store-manager/today-tasks?store_id=&date=` | 无 | 取今日任务 |
| PUT | `/api/store-manager/tasks/{task_id}/status` | 无 | 更新任务状态（不存在→404） |
| POST | `/api/store-manager/tasks/{task_id}/review` | 无 | 提交复盘（不存在→404） |
| POST | `/api/store-manager/admin/reports/{report_id}/mark` | **X-Admin-Key** | 后台人工标记 |

- 响应统一 `{"code":1000,"msg":"success","data":...}`，与小程序 `utils/managerApi.js` 对齐。
- 前 7 个为店长侧（本期不做复杂权限，后续接小程序登录态）；第 8 个后台接口已加轻量保护。

---

## 4. 独立 SQLite 路径

- 环境变量：`STORE_MANAGER_DB_PATH`
- 默认值：`/opt/meiye-wuyou/data/store_manager_workbench.db`
- 行为：`storage.py` 每次连接调用 `init_db()` **自动建表**（`store_manager_reports`、`store_manager_tasks`）+ 自动建索引；**不读 `DATABASE_URL`、不进主库、不碰 SQLAlchemy ORM**。
- 后台鉴权环境变量：`STORE_MANAGER_ADMIN_KEY`（未配置时 `/admin/*` 默认拒绝，安全锁定）。

> 部署前置：确保 `/opt/meiye-wuyou/data/` 存在且可写、纳入备份（由扣子在阿里云配置）。

---

## 5. 冒烟测试结果

方式：用 `TestClient` 将 `store_manager_router` 挂到最小 FastAPI app（隔离 weasyprint/SQLAlchemy 等无关依赖），临时 DB + 测试 admin key，覆盖全部端点与边界。

**结果：17 / 17 全通过。**

| 项 | 结果 |
|----|------|
| POST 提交诊断 200 / code=1000 | ✅ |
| 核心问题=3 / 今日任务 3-5 / display 7 段 | ✅ |
| GET 报告 id 一致 / 不存在→404 | ✅ |
| GET history 含刚生成报告 | ✅ |
| POST generate 今日任务 3-5 | ✅ |
| GET today-tasks 可读 | ✅ |
| PUT status 生效 / 不存在→404 | ✅ |
| POST review 200 | ✅ |
| admin 无 key→401 / 错 key→401 / 正确 key→200 | ✅ |
| 8 个端点全部注册 | ✅ |

补充验证：
- `py_compile` 全部源文件语法通过；
- 规则引擎此前已单独实跑（3 核心问题 / 3 任务 / 7 段文本 / 目标完成率 66.7%）。

> 说明：因当前环境未安装 weasyprint（系统级依赖），未做"整库一次性启动"冒烟；store-manager 模块与 weasyprint 无任何依赖关系，已通过隔离挂载完整验证。整库启动冒烟建议在已装齐依赖的部署前环境由扣子执行。

---

## 6. 是否影响 V0.1.1

**不影响。**
- 新接口前缀 `/api/store-manager`，与 `/api/diagnoses`、`/api/monthly-checkups` 及 5 个小程序接口（`auth/wechat-login`、`stores/profile`、`content/generate`、`ai/chat`、`coach/webview-token`）**无路由重叠**；
- 未改 `diagnoses.py`、`monthly.py`、`admin.py`、`weapp.py`、`scoring.py`、`mba_models.py`、`models.py`、`schemas.py`、`database.py`；
- 未改主库 schema、未做迁移；工作台数据写入独立 SQLite。
- 唯一改动的现有文件是 `main.py`（新增 2 行）。

---

## 7. 回滚方式

1. 删除 `main.py` 中新增的 2 行（import + include_router）→ `/api/store-manager/*` 立即下线，其余服务不受影响；
2. 删除 `backend/app/store_manager/` 子包目录；
3. 工作台独立 SQLite 文件可保留或删除，**不影响主库**；
4. 未改主库 schema、未迁移，**无数据迁移回滚**；
5. Git 层面：本次施工集中在独立 commit，可直接 `git revert`。

---

## 8. 下一步联调建议

1. **PR 审核**：本次施工已建 PR（见仓库），**先不 merge**，等审核 + 拍板。
2. **前后端联调**（建议在合并前的预发/测试环境）：
   - 小程序 `utils/config.js` 把工作台 `MOCK_MODE` 切为 `false`，`apiBaseUrl` 指向测试后端；
   - 走完小闭环：填 15 项 → 生成报告 → 看 3 问题 → 生成今日任务 → 改状态 → 复盘 → 历史；
   - 校验前端解析后端 `display_text` / `structured_json` 字段一致。
3. **store_id 口径**对齐（小程序传入值，见评估报告第 16 节问题 4）。
4. **部署前**（扣子）：装齐依赖（含 weasyprint 系统库）、做整库启动冒烟、配置 `STORE_MANAGER_DB_PATH` 与 `STORE_MANAGER_ADMIN_KEY`、确认数据目录可写可备份。
5. 整库冒烟 + 联调通过后，再由扣子在阿里云拉服务；上线由吴哥最终拍板。

---

## 9. 边界确认（本施工阶段）

- ✅ 未部署、未上生产、未改线上服务
- ✅ 未改数据库主库、未建主库表、未迁移
- ✅ 未启 cron、未接企微
- ✅ 未接大模型（规则引擎 + 模板输出）
- ✅ 未自动写 memory_tree / Nyx / knowledge_workflow
- ✅ 未接 OpenClaw / Hermes / PraisonAI / ES / 7 大库召回
- ✅ 未做美容师档口 / 老板档口 / 顾客档案 / 品相表
- ✅ 未触碰 V0.1.1 诊断稳定版

---

## 10. 当前阶段定盘

- 前端 PR：已创建，不 merge；
- 后端评估：通过；
- **后端施工：完成（仅分支内），冒烟 17/17 通过；**
- 部署：禁止；上线：禁止。

> 本阶段定为：**后端分支内施工完成，已建 PR 待审核，未部署。**
