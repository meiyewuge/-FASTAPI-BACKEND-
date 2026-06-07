# 店长工作台 V0.1.2 · 前后端联调预案

> 文件：`STORE_MANAGER_V0_1_2_FRONTEND_BACKEND_INTEGRATION_PLAN.md`
> 阶段：**联调预案（不部署、不 merge、不上线）**
> 目的：把已分别完成的「前端 MOCK 线」与「后端分支线」合二为一的联调方案，供测试环境联调前审核。
> 状态：两条线均为分支 + PR，**均未合并、均未部署**。

---

## 1. 前端 PR 信息

| 项 | 值 |
|----|----|
| 仓库 | `meiyewuge/MWUZS-MINIAPP` |
| 分支 | `claude/quirky-turing-wHaIa` |
| PR 地址 | https://github.com/meiyewuge/MWUZS-MINIAPP/pull/1 |
| 是否已 merge | **否**（open，mergeable_state: clean） |
| head commit | `26f5bcf` |
| 规模 | 40 文件，+1595 / -1 |

---

## 2. 后端 PR 信息

| 项 | 值 |
|----|----|
| 仓库 | `meiyewuge/-FASTAPI-BACKEND-` |
| 分支 | `claude/quirky-turing-wHaIa` |
| PR 地址 | https://github.com/meiyewuge/-FASTAPI-BACKEND-/pull/1 |
| 是否已 merge | **否**（open，mergeable_state: clean） |
| head commit | `1297912` |
| 规模 | 8 文件，+1041 |

---

## 3. 前后端接口对照表

前端 `utils/managerApi.js` ↔ 后端 `app/store_manager/router.py`（前缀 `/api/store-manager`）：

| 业务 | 前端方法 (managerApi.js) | 后端接口 | 鉴权 | 状态 |
|------|--------------------------|----------|------|------|
| 提交诊断 | `submitMonthlyDiagnosis(payload)` | `POST /api/store-manager/monthly-diagnoses` | 无 | ✅ 已对齐 |
| 获取报告 | `getMonthlyDiagnosis(reportId)` | `GET /api/store-manager/monthly-diagnoses/{report_id}` | 无 | ✅ 已对齐 |
| 历史报告 | `getHistory(storeId)` | `GET /api/store-manager/history?store_id=` | 无 | ✅ 已对齐 |
| 生成今日任务 | `generateTodayTasks(params)` | `POST /api/store-manager/today-tasks/generate` | 无 | ✅ 已对齐 |
| 获取今日任务 | `getTodayTasks(storeId)` | `GET /api/store-manager/today-tasks?store_id=&date=` | 无 | ✅ 已对齐 |
| 更新任务状态 | `updateTaskStatus(taskId, status)` | `PUT /api/store-manager/tasks/{task_id}/status` | 无 | ✅ 已对齐 |
| 提交复盘 | `submitTaskReview(taskId, review)` | `POST /api/store-manager/tasks/{task_id}/review` | 无 | ✅ 已对齐 |
| 后台标记 | （前端 MVP **暂未调用**） | `POST /api/store-manager/admin/reports/{report_id}/mark` | **X-Admin-Key** | ⚠️ 后端就绪，前端本期不接 |

**响应契约**：后端统一返回 `{"code":1000,"msg":"success","data":...}`；前端 `managerApi` 取 `res.data`。报告体含 `report_id / display_text / structured_json(core_issues / weekly_actions / today_tasks / staff_suggestions / risk_notes)`，与前端页面解析字段一致（冒烟已验证）。

> 待联调核对点：`store_id` 口径（前端目前用 `store_profile.store_id || id || 'default_store'`，后端按自由字符串存储）。

---

## 4. 前端从 MOCK 切换真实接口的点

**核心结论：工作台已有独立开关 `MOCK_MODE`，切真接口只需翻为 `false`，不新增、不碰全局 `mockMode`。**

`utils/config.js` 现状：

```js
mockMode: false,   // 全局/主链路开关（内容、AI问答、经营体检）—— 不动
MOCK_MODE: true,   // 店长工作台专用开关 —— 联调时改为 false
```

- `managerApi.js` 内部判断的是 `CONFIG.MOCK_MODE`，**与全局 `mockMode` 完全独立**。因此：
  - 切换点：`MOCK_MODE: true → false`（仅影响工作台）；
  - **不需要**再新增 `STORE_MANAGER_MOCK_MODE`（`MOCK_MODE` 本身就是工作台专用开关）；
  - **不允许**改全局 `mockMode`（保持现有内容/AI问答/经营体检的行为不变）。
- 切 `false` 后，`managerApi` 会走 `request()`：
  - 需把 `config.apiBaseUrl` 指向联调后端（测试环境地址）；
  - `request.js` 会带 `Authorization: Bearer <token>`，store-manager 店长侧接口本期不校验 token，可正常调用；
  - 微信开发者工具需勾选「不校验合法域名」或把测试域名加入 request 合法域名。
- 影响面：仅 `pages/manager/*`；现有功能零影响。

> 可选（非必须）：若想命名更直观，可把 `MOCK_MODE` 改名为 `STORE_MANAGER_MOCK_MODE` 并同步 `managerApi.js` —— 属精装修，本期不做也不影响联调。

---

## 5. 后端需要的环境变量

| 变量 | 作用 | 建议值 / 说明 |
|------|------|---------------|
| `STORE_MANAGER_DB_PATH` | 工作台独立 SQLite 路径 | 生产：`/opt/meiye-wuyou/data/store_manager_workbench.db`；联调可用本地可写路径（如 `./data/store_manager_workbench.db` 或 `/tmp/...`） |
| `STORE_MANAGER_ADMIN_KEY` | `/admin/*` 鉴权密钥 | 联调/生产必须显式设置；**未设置时 `/admin/*` 默认拒绝（401）** |

> 这两个变量与现有后端 `.env`（`DATABASE_URL`、`ADMIN_KEY` 等）相互独立，不冲突。工作台不读 `DATABASE_URL`、不进主库。

---

## 6. 本地 / 测试环境联调步骤

> 前提：在装齐依赖的环境执行（`pip install -r backend/requirements.txt`，含 weasyprint 系统库）。

1. **配置后端环境变量**
   ```bash
   export STORE_MANAGER_DB_PATH=./data/store_manager_workbench.db   # 可写路径
   export STORE_MANAGER_ADMIN_KEY=<联调用密钥>
   ```
2. **启动后端**
   ```bash
   cd backend && python run.py      # uvicorn app.main:app :8000
   ```
3. **后端冒烟**
   - `GET /health` → `{"status":"ok"}`；
   - 或直接打 store-manager：`POST /api/store-manager/monthly-diagnoses`（带 15 项 form_data）→ 应返回 `code:1000` + 报告。
4. **小程序切真实接口**
   - `utils/config.js`：`MOCK_MODE = false`；`apiBaseUrl` 指向测试后端；
   - 开发者工具勾选「不校验合法域名」（或配置 request 合法域名）。
5. **走小闭环（11 步）**
   1. 首页 → 店长工作台；
   2. 本月诊断入口 → 填 15 项数据；
   3. 提交 → 生成报告（POST monthly-diagnoses）；
   4. 报告页显示 3 个核心问题（GET monthly-diagnoses/{id}）；
   5. 生成今日任务（POST today-tasks/generate）；
   6. 今日清单显示 3-5 条（GET today-tasks）；
   7. 任务详情；
   8. 修改任务状态（PUT tasks/{id}/status）；
   9. 提交复盘（POST tasks/{id}/review）；
   10. 历史报告可见（GET history）；
   11. （可选）后台标记需带 `X-Admin-Key`（POST admin/reports/{id}/mark）。
6. **字段一致性核对**：前端解析的 `display_text` 7 段、`structured_json` 各数组与后端返回一致。

---

## 7. 风险点

| # | 风险 | 说明 / 缓解 |
|---|------|-------------|
| 1 | weasyprint 环境依赖 | 整库启动需 weasyprint 系统库（cairo/pango）；联调环境须装齐，否则 `app.main` 导入失败（与 store-manager 无关，但会挡整库启动）。store-manager 模块本身不依赖它。 |
| 2 | 独立 SQLite 权限/路径 | `STORE_MANAGER_DB_PATH` 目录须存在且可写并纳入备份；`/opt/meiye-wuyou/data/` 在阿里云需提前创建授权 |
| 3 | admin key 未配置即拒绝 | 安全设计：`STORE_MANAGER_ADMIN_KEY` 未设时 `/admin/*` 一律 401；联调/生产须显式设置 |
| 4 | 小程序 request 合法域名 | 真机/体验版需把后端域名加入「request 合法域名」；开发者工具可临时关闭校验 |
| 5 | `api.beautypeaceai.com` 备案恢复状态 | 上线依赖该域名 HTTPS + 备案就绪；备案/恢复未完成前不要切生产域名，联调先用测试地址 |
| 6 | `store_id` 口径未最终对齐 | 前后端需约定小程序传入值（openid / 门店 id / 固定值），见第 3 节 |
| 7 | token 行为 | store-manager 店长侧接口本期不校验 token；后续接登录态时需同步前后端 |

---

## 8. 回滚方案

| 场景 | 操作 |
|------|------|
| 前端未合并 | 直接不 merge PR；或关闭 PR；分支保留不影响主干 |
| 后端未合并 | 同上 |
| 前端已合并需回退 | `git revert` 该合并；或把 `MOCK_MODE` 改回 `true`（工作台立即回到本地 mock，不依赖后端） |
| 后端已合并需回退 | 删 `main.py` 的 2 行注册（`/api/store-manager/*` 立即下线）；或 `git revert`；删 `app/store_manager/` 子包 |
| 数据层回滚 | 工作台独立 SQLite 可直接停用/删除文件，**不影响主库、不影响 V0.1.1** |
| 紧急止血 | 后端：去掉 `include_router(store_manager_router)` 即下线工作台；前端：`MOCK_MODE=true` 即与后端解耦 |

> 因后端未改主库 schema、未迁移，**无数据迁移回滚**；前端未改全局 `mockMode`，回退零副作用。

---

## 9. 部署前必须确认事项（逐项打勾后才进部署）

- [ ] 微信开发者工具实测通过（编译 + 11 步小闭环 + 今日清单状态 chip）
- [ ] 前后端联调通过（MOCK_MODE=false 下走通全链路，字段一致）
- [ ] `store_id` 口径已对齐
- [ ] 后端环境变量已确认（`STORE_MANAGER_DB_PATH` 可写可备份、`STORE_MANAGER_ADMIN_KEY` 已设）
- [ ] 整库启动冒烟通过（含 weasyprint 依赖的部署前环境）
- [ ] `api.beautypeaceai.com` 备案/HTTPS/合法域名就绪
- [ ] ChatGPT 审核通过
- [ ] 吴哥拍板
- [ ] 扣子输出部署计划后再施工

---

## 10. 当前阶段定盘

```text
前端 PR：已建，未合并（MWUZS-MINIAPP #1）
后端 PR：已建，未合并（-FASTAPI-BACKEND- #1）
前端 MOCK：通过（18/18 + 修复回归 5/5）
后端分支施工：通过（冒烟 17/17）
联调：本预案就绪，尚未执行
部署：未做 / 上线：未做
```

> 本阶段定为：**联调预案就绪。下一步由吴哥决定是否进入「测试环境联调」。在联调通过 + 审核 + 拍板前，两个 PR 均不合并、不部署。**
