# STAGING 部署清单路径修正报告 · STAGING_DEPLOY_CHECKLIST_PATH_FIX_REPORT

> 仅改部署清单文档与打包：**未写业务代码、未部署、未碰 production**。分支 `claude/v4-staging`。
> 起因：ChatGPT 审核发现清单多处用 `/opt/v4-video-engine/...`，易与 production 路径混淆（高风险）。

## 逐条落实（对照 10 项要求）

### 1. 是否已填入前端 commit b0e0741 —— ✅ 是
- 前端分支 `qoder/v4-frontend-workbench`，commit 由 `<WAIT_QODER_COMMIT>` 改为 **`b0e0741`**（代码版本节 + 部署顺序 Step10 + 报告模板三处一致）。

### 2. 是否已统一 staging backend 路径 —— ✅ 是
- 全部统一为 **`/opt/v4-video-engine-staging/backend/`**。
- 备份示例 → `/opt/v4-video-engine-staging/backend.bak.<时间戳>/`。
- 拉码 / migration / backfill 的 `cd` 均指向该目录。

### 3. 是否已统一 staging frontend 路径 —— ✅ 是
- 全部统一为 **`/opt/v4-video-engine-staging/frontend/`**。
- 前端备份示例 → `/opt/v4-video-engine-staging/frontend.bak.<时间戳>/`。
- build / dist 部署明确在 staging frontend 目录。

### 4. 是否已统一 staging DB 路径 —— ✅ 是
- 全部统一为 **`/opt/v4-video-engine-staging/backend/meiye_v4_staging.db`**。
- DB 备份 / 还原 / migration 脚本 `sqlite3.connect(...)` / 报告模板均用该绝对路径。

### 5. 是否已统一 staging storage/upload 路径 —— ✅ 是
- `.env`：`STORAGE_DIR=/opt/v4-video-engine/storage-staging/videos`、`UPLOAD_DIR=/opt/v4-video-engine/storage-staging/uploads`。
- Nginx 静态：`/static/videos/ → /opt/v4-video-engine/storage-staging/videos/`、`/static/uploads/ → /opt/v4-video-engine/storage-staging/uploads/`（明确不指向 production storage）。
- `STORAGE_BASE_URL/UPLOAD_BASE_URL` 改为「指向 staging 静态入口、勿指向 production」并保留「必须 https 否则 2002」提示。
- 备份新增 `storage-staging` 目录。
- 特别标注易混点：**后端/前端/DB 在 `…-staging/` 目录；存储在 `…/storage-staging/` 目录**。

### 6. 是否已强化 production 禁止项 —— ✅ 是
- 清单开头新增「🚨 生产零影响红线」：
  - **允许**：`/opt/v4-video-engine-staging/`、`/opt/v4-video-engine/storage-staging/`、`v4-video-engine-staging.service`、`19180/19181`、`meiye_v4_staging.db`。
  - **严禁**：`/opt/v4-video-engine/backend/`、`/opt/v4-video-engine/frontend/`、`/opt/v4-video-engine/backend/meiye_v4.db`、`v4-video-engine.service`、`video.beautypeaceai.com` production。
- Nginx 节补「以当前 19181 入口正在使用的 Nginx 配置为准；禁止修改 production nginx 配置」。
- 部署顺序标注「勿停 `v4-video-engine.service`」；health/info 用 staging 后端 19180。
- 报告模板 production 零影响检查项细化到具体 production 资源名。

### 7. 是否已重新打包给 Coze —— ✅ 是
- 重新生成 `STAGING_V4_FULL_DEPLOY_CHECKLIST.md`（路径全部修正）。
- 重新打包 `V4_STAGING_DEPLOY_for_Coze_CURRENT_20260625.zip`，含：
  1. `STAGING_V4_FULL_DEPLOY_CHECKLIST.md`
  2. `BACKEND_V4_PAGE_REDESIGN_P0_REPORT.md`
  3. `BACKEND_V4_P1_REMIX_CODE_REPORT.md`
  4. `BACKEND_V4_P0A_P0B_DIRECTOR_ENGINE_REPORT.md`

### 8. 是否可以交 Coze 执行 staging 部署 —— ✅ 可以
- 路径已全部消歧，红线明确，前端 commit 已填 `b0e0741`。
- 真实 compose 仍保持 `ENABLE_COMPOSE=false`（解锁需满足 7 条件 + 吴哥手动确认）。
- Coze 可照修正版清单一次性部署后端 P0/P1/P0-A/P0-B + 前端到 staging。

## 校验
- 清单内已无指向 production 后端/前端/生产库的 staging 操作路径；剩余 `/opt/v4-video-engine/backend|frontend|meiye_v4.db` 仅出现在「红线禁止项」与「报告 production 零影响检查项」中（故意列出，用于警示）。
- commit 号见推送结果。
