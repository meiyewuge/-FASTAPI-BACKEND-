# STAGING V4 全量部署清单（给 Coze）· STAGING_V4_FULL_DEPLOY_CHECKLIST

> **这是部署清单，本文件本身不执行部署。** 待 Qoder 前端完成并通过 ChatGPT 审核后，Coze 按此一次性部署后端 P0/P1/P0-A/P0-B + 前端。
> **铁律：只动 staging，绝不碰 production。真实 compose 部署后保持锁定（ENABLE_COMPOSE=false），不自动解锁。**

---

## 🚨 生产零影响红线（务必先读）

**本清单所有命令只允许作用于以下 staging 资源：**
- 后端目录：`/opt/v4-video-engine-staging/backend/`
- 前端目录：`/opt/v4-video-engine-staging/frontend/`
- 视频/上传存储：`/opt/v4-video-engine/storage-staging/videos/`、`/opt/v4-video-engine/storage-staging/uploads/`
- systemd 服务：`v4-video-engine-staging.service`
- staging 入口端口：`19180`（后端）/ `19181`（nginx 对外）
- staging 数据库：`/opt/v4-video-engine-staging/backend/meiye_v4_staging.db`

**🚫 严禁作用于以下 production 资源（碰任意一项即视为事故）：**
- `/opt/v4-video-engine/backend/`（production 后端）
- `/opt/v4-video-engine/frontend/`（production 前端）
- `/opt/v4-video-engine/backend/meiye_v4.db`（production DB）
- `v4-video-engine.service`（production 服务）
- `video.beautypeaceai.com` production 对外服务 / production nginx

> 注意路径易混点：**后端/前端/DB 在 `…-staging/` 目录下**；**存储在 `…/storage-staging/` 目录下**（注意是 `storage-staging`，不是 `-staging/storage`）。

---

## 一、代码版本

**后端分支**：`claude/v4-staging`

关键 commit（按里程碑，部署取分支 HEAD 即含全部）：
| 里程碑 | commit |
|----|----|
| P0 页面重构（批量上传/上传进陈列面/批量裂变/临时存储/清理） | `7184bbd` |
| P0 业务资产回流层（workflow_runs/信号/候选池） | `7e6e840` |
| P0 收口（删除租户隔离 + storage 分角色） | `d49b07d` |
| P1 B台裂变真实工作流（duration_seconds + source_video_ids + 1:10） | `143e6eb` |
| P0-A 安全止血 + P0-B Director Engine（preview/熔断锁/ledger） | `7922fe3` |
| 前端接口合同收口（当前文档真源） | `f1981a3` |
> 部署前请 `git fetch && git checkout claude/v4-staging && git pull`，并记录实际 HEAD commit 到部署报告。

**前端分支**：`qoder/v4-frontend-workbench`
- 前端 commit：**`b0e0741`**（Qoder 已完成 + 审核通过）

---

## 二、部署前备份（强制）

```bash
TS=$(date +%Y%m%d_%H%M%S)
# 后端代码（staging）
cp -r /opt/v4-video-engine-staging/backend            /opt/v4-video-engine-staging/backend.bak.$TS
# 前端目录（staging）
cp -r /opt/v4-video-engine-staging/frontend           /opt/v4-video-engine-staging/frontend.bak.$TS
# SQLite DB（staging）
cp /opt/v4-video-engine-staging/backend/meiye_v4_staging.db  /opt/v4-video-engine-staging/backend/meiye_v4_staging.db.bak.$TS
# .env（staging）
cp /opt/v4-video-engine-staging/backend/.env          /opt/v4-video-engine-staging/backend/.env.bak.$TS
# 视频/上传存储（staging）
cp -r /opt/v4-video-engine/storage-staging            /opt/v4-video-engine/storage-staging.bak.$TS
# Nginx（staging 配置，以实际为准，见第六节）
cp /etc/nginx/conf.d/v4-staging.conf          /opt/v4-video-engine-staging/nginx.v4-staging.conf.bak.$TS
```

**明确禁止**：
- ❌ 不碰 production 代码 / 不重启 production service
- ❌ 不改 production DB / 不改 production nginx
- ❌ 本次所有操作仅限 staging 目录、staging service、staging DB、staging nginx

---

## 三、DB migration 汇总

> 新表由后端启动 `Base.metadata.create_all` **自动创建**（无需手工建表）。
> 存量表新增列：SQLite **不支持** `ADD COLUMN IF NOT EXISTS`，必须先检测再加。下方给出安全检测脚本 + 等价 SQL。

### 3.1 新表（自动建，全新库无需手工）
`invite_codes` · `uploads` · `admin_users` · `workflow_runs` · `video_feedback_signals` · `knowledge_candidates` · `director_plans` · `cost_ledger`
> 若 staging 已有旧版 `invite_codes`（无 phone 列），见 3.2。

### 3.2 存量表新增列（按需 ALTER）

**强烈建议用「检测后再加」的幂等脚本（SQLite）**：
```python
# migrate_staging.py（一次性，跑完即弃）
import sqlite3
db = sqlite3.connect("/opt/v4-video-engine-staging/backend/meiye_v4_staging.db")
def addcol(table, col, ddl):
    cols = [r[1] for r in db.execute(f"PRAGMA table_info({table})")]
    if col not in cols:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
        print(f"  + {table}.{col}")
    else:
        print(f"  = {table}.{col} 已存在，跳过")

# videos（P0/P1）
addcol("videos","source_type",     "source_type VARCHAR(16) NOT NULL DEFAULT 'generated'")
addcol("videos","storage_status",  "storage_status VARCHAR(16) NOT NULL DEFAULT 'active'")
addcol("videos","expires_at",      "expires_at DATETIME")
addcol("videos","origin_file_id",  "origin_file_id VARCHAR(40)")
addcol("videos","parent_video_id", "parent_video_id INTEGER")
addcol("videos","batch_id",        "batch_id VARCHAR(40)")
addcol("videos","thumbnail_path",  "thumbnail_path VARCHAR(512)")
addcol("videos","duration_seconds","duration_seconds FLOAT")          # P1
# tasks（P0/P0-A）
addcol("tasks","batch_id",         "batch_id VARCHAR(40)")
addcol("tasks","run_id",           "run_id VARCHAR(40)")
addcol("tasks","provider_job_id",  "provider_job_id VARCHAR(64)")     # P0-A
# tenants（P0 订阅/试用）
addcol("tenants","subscription_status","subscription_status VARCHAR(16) NOT NULL DEFAULT 'trial'")
addcol("tenants","trial_remaining","trial_remaining INTEGER NOT NULL DEFAULT 3")
# uploads（若旧版已存在该表）
addcol("uploads","storage_status", "storage_status VARCHAR(16) NOT NULL DEFAULT 'active'")
addcol("uploads","expires_at",     "expires_at DATETIME")
# invite_codes（若旧版已存在该表）
addcol("invite_codes","phone",     "phone VARCHAR(32)")
db.commit(); db.close()
print("migration done")
```
运行：`cd backend && python migrate_staging.py`（幂等，可重复跑；已存在的列自动跳过）。

**等价裸 SQL（仅当列确实不存在时执行，已存在会报错）**：
```sql
ALTER TABLE videos ADD COLUMN source_type VARCHAR(16) NOT NULL DEFAULT 'generated';
ALTER TABLE videos ADD COLUMN storage_status VARCHAR(16) NOT NULL DEFAULT 'active';
ALTER TABLE videos ADD COLUMN expires_at DATETIME;
ALTER TABLE videos ADD COLUMN origin_file_id VARCHAR(40);
ALTER TABLE videos ADD COLUMN parent_video_id INTEGER;
ALTER TABLE videos ADD COLUMN batch_id VARCHAR(40);
ALTER TABLE videos ADD COLUMN thumbnail_path VARCHAR(512);
ALTER TABLE videos ADD COLUMN duration_seconds FLOAT;
ALTER TABLE tasks  ADD COLUMN batch_id VARCHAR(40);
ALTER TABLE tasks  ADD COLUMN run_id VARCHAR(40);
ALTER TABLE tasks  ADD COLUMN provider_job_id VARCHAR(64);
ALTER TABLE tenants ADD COLUMN subscription_status VARCHAR(16) NOT NULL DEFAULT 'trial';
ALTER TABLE tenants ADD COLUMN trial_remaining INTEGER NOT NULL DEFAULT 3;
ALTER TABLE uploads ADD COLUMN storage_status VARCHAR(16) NOT NULL DEFAULT 'active';
ALTER TABLE uploads ADD COLUMN expires_at DATETIME;
ALTER TABLE invite_codes ADD COLUMN phone VARCHAR(32);
```
> PostgreSQL 可用 `ADD COLUMN IF NOT EXISTS`，且 `DATETIME→TIMESTAMP`、`FLOAT` 通用。

### 3.3 回滚方案
- **首选**：还原 staging DB 备份 `cp /opt/v4-video-engine-staging/backend/meiye_v4_staging.db.bak.$TS /opt/v4-video-engine-staging/backend/meiye_v4_staging.db`（最稳）。
- 列回滚：SQLite < 3.35 不支持 `DROP COLUMN`，**保留多余空列即可，不影响旧逻辑**；≥3.35 可 `ALTER TABLE x DROP COLUMN y`。
- 新表回滚：`DROP TABLE director_plans; DROP TABLE cost_ledger; ...`（或直接还原 DB 备份）。

---

## 四、回填脚本（duration_seconds）

```bash
cd /opt/v4-video-engine-staging/backend
python -m tasks.backfill_duration
# 输出：[backfill_duration] scanned=N updated=M unknown(NULL)=K
```
说明：
- **只跑 staging**。
- 扫 `storage_status='active' 且 duration_seconds IS NULL` 的视频，ffprobe 本地文件回填。
- 成功 → 写入秒数；找不到文件 / ffprobe 失败 → 保持 **NULL**。
- **`duration_seconds=NULL 或 <30` 不计入 B台合格源视频**（裂变不会选它）。
- 记录 scanned/updated/unknown 到部署报告。

---

## 五、.env 新增项

> pydantic-settings 大小写不敏感，字段名 → 同名大写环境变量。**不要覆盖** `JWT_SECRET / ADMIN_KEY / VIDEO_API_KEY`（保留 staging 既有值）。

```ini
# ---- A台 compose 熔断锁（P0-A）：部署后保持 false，不自动解锁 ----
ENABLE_COMPOSE=false
# ---- Seedance / compose 标准参数（P0-B）----
COMPOSE_GENERATE_AUDIO=true
COMPOSE_RATIO=9:16
COMPOSE_RESOLUTION=1080p
COMPOSE_WATERMARK=false
COMPOSE_MAX_IMAGES=9
VOLC_MODEL=doubao-seedance-2-0-260128     # 与火山控制台一致（RISK-2，勿写错）
# ---- 存储 / 上传（图片 preview 依赖 HTTPS 公网 URL）----
STORAGE_ENABLED=true
STORAGE_DIR=/opt/v4-video-engine/storage-staging/videos
UPLOAD_DIR=/opt/v4-video-engine/storage-staging/uploads
# 下面两个为「公网 HTTPS 静态访问基址」，必须指向 staging 静态入口（19181 nginx 暴露的 /static/...），
# 以实际 staging 域名/路径为准，勿指向 production（video.beautypeaceai.com）：
STORAGE_BASE_URL=https://<staging静态域名>/static/videos
UPLOAD_BASE_URL=https://<staging静态域名>/static/uploads   # 必须 https，否则 A台 preview 图片校验失败(2002)
# ---- 鉴权（Patch4/6）----
JWT_SECRET=<保留 staging 既有值，勿覆盖>
ADMIN_KEY=<保留 staging 既有值，勿覆盖>
AUTH_REQUIRED=true
```

> **关于模板版本**：`DIRECTOR_PROMPT_VERSION / STYLE_PRESET_VERSION / NEGATIVE_WORDS_VERSION` 当前**写死在代码**（`prompt_templates/`：`director_prompt_v1` / `style_preset_v1` / `beauty_safe_v1`），**无需也不要写进 .env**（每条 director_plan 已自动记录这三个版本，可追溯）。如未来要用 .env 覆盖版本，需先在代码加对应 settings 字段——本轮不做。

**注意**：
- `ENABLE_COMPOSE` **默认 false**；部署后**不要自动解锁**真实 compose（解锁条件见第十节）。

---

## 六、Nginx / 静态路径

确认 staging nginx（**staging 入口 19181 对外；后端 19180**；只改 staging 配置，禁止改 production nginx）：
- `location /api/ { proxy_pass http://127.0.0.1:19180; }`（staging 后端端口 19180；以 staging service 实际监听端口为准）。
- `location /static/videos/ { alias /opt/v4-video-engine/storage-staging/videos/; }`（**指向 storage-staging**，勿指向 production storage）。
- `location /static/uploads/ { alias /opt/v4-video-engine/storage-staging/uploads/; }`（同上）。
- `client_max_body_size 600m;`（视频 ≤500MB + 余量；批量总量 ≤2GB 由后端拦，nginx 单请求放够即可）。
- **图片 URL 必须公网 HTTPS 可访问**（`UPLOAD_BASE_URL=https://...`）——否则 A台 preview 图片校验返回 2002。
- 上传图片**不再 502**：确认 `proxy_read_timeout`/`client_max_body_size` 足够，且 `/opt/v4-video-engine/storage-staging/uploads/` 目录权限可读。
- 配置文件：`/etc/nginx/conf.d/v4-staging.conf`；**如实际 staging 配置文件名不同，以当前 19181 入口正在使用的 Nginx 配置为准；禁止修改 production nginx 配置。**
- 改完 `nginx -t && systemctl reload nginx`（仅 **staging 配置**，不动 production）。

---

## 七、系统依赖

确认 staging 机：
- `ffmpeg -version` 可用（裂变 / 拼接 / 封面）。
- `ffprobe -version` 可用（duration_seconds 回填 / 探测）。
- Python venv 已建并装 `requirements.txt`（含 `python-multipart`）。
- Node / npm 可用（前端 build）。
- systemd service 存在；**staging service 名称**：`v4-video-engine-staging`（以实际为准，部署报告写明）。
- CJK 字体 `/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc`（裂变 drawtext）。

---

## 八、部署顺序

```
1.  systemctl stop v4-video-engine-staging                       # 停 staging 后端（勿停 v4-video-engine.service）
2.  执行「二、备份」全部备份
3.  cd /opt/v4-video-engine-staging/backend
    git fetch && git checkout claude/v4-staging && git pull       # 拉后端代码
4.  保留 .env（恢复 /opt/v4-video-engine-staging/backend/.env.bak，
    确认 JWT_SECRET/ADMIN_KEY/VIDEO_API_KEY 未变；补「五」新增项）
5.  cd /opt/v4-video-engine-staging/backend && python migrate_staging.py   # DB migration（幂等）
6.  cd /opt/v4-video-engine-staging/backend && python -m tasks.backfill_duration   # 回填 duration_seconds
7.  systemctl start v4-video-engine-staging                       # 启动 staging 后端
8.  curl http://127.0.0.1:19180/health                           # staging 后端，期望 {"status":"ok",...}
9.  curl http://127.0.0.1:19180/api/info                         # 确认 env=staging（app_env）
10. cd /opt/v4-video-engine-staging/frontend
    git checkout qoder/v4-frontend-workbench && git pull          # 前端 commit b0e0741
11. npm ci && npm run build                                       # 在 staging frontend 目录
12. 部署 dist 到 staging 前端目录（/opt/v4-video-engine-staging/frontend 下的发布目录）
13. nginx -t && systemctl reload nginx                           # reload staging nginx（19181 入口）
14. 执行「九、验证清单」全链路验证
```

---

## 九、验证清单

### A台 preview（不花钱）
- [ ] 登录拿 JWT
- [ ] `POST /api/uploads/batch` 上传图片，拿 `file_id`
- [ ] `POST /api/compose/preview` 返回 `director_plan_id`
- [ ] 返回 `image_roles`（第1张 first_frame，其余 reference_image）
- [ ] 返回 `estimated_cost`（如 1080p 15s = 37.20）
- [ ] **未调用火山**（火山控制台无新任务 / 后端无 submit 日志）
- [ ] **未扣费**（cost_ledger 仅 estimate，无 precharge）

### A台 compose 锁态
- [ ] `POST /api/compose {director_plan_id, confirmed_cost:true}` → `code:4031`
- [ ] message =「生成通道维护中，暂不可用。」
- [ ] 前端 A台生成按钮置灰并显示该文案

### B台裂变
- [ ] 上传 3 个 ≥30 秒视频（回填后 `duration_seconds>=30`）
- [ ] B台按钮可用（合格源 ≥3）
- [ ] 请求体用 `source_video_ids`
- [ ] `POST /api/b/batch-generate` 返回 `batch_id`、`total_outputs=30`、`cost=0`
- [ ] `GET /api/b/batch/{batch_id}` done 后 `GET /api/videos?type=viral&batch_id=xxx` 刷新出 30 条

### 候选池
- [ ] `POST /api/videos/{id}/feedback` 生成 `candidate(status=pending)`
- [ ] super_admin `GET /api/admin/knowledge-candidates` 可见
- [ ] user / invite_admin 调该接口 → 403，前端不显示候选池

### Patch6
- [ ] `GET /api/me` 返回正确 role
- [ ] super_admin/invite_admin `POST /api/admin/invite/generate` 发码正常
- [ ] user 调发码端点 → 403

---

## 十、解锁真实 compose 的条件

> **真实 compose 不能默认启用。** 部署后 `ENABLE_COMPOSE=false`。
> 只有以下 7 条全部满足、且**吴哥手动确认**后，才允许改 `ENABLE_COMPOSE=true` 并 `systemctl restart v4-video-engine-staging`：

1. preview 流程通过（导演稿 / 提示词 / 估价正确）。
2. 图片 role 正常（first_frame / reference_image，HTTPS 可达）。
3. 计费预扣正常（拿 provider_job_id 立即 precharge）。
4. failed 自动 refund 正常。
5. recovery 不重复 submit（锁态跳过 compose；有 provider_job_id 不二次提交）。
6. provider_job_id 持久化正常。
7. **吴哥手动确认**。

解锁后建议先做**一条小时长（如 4-8 秒）受控真生成**，盯 `cost_ledger`（precharge 金额 ≈ 火山实际扣费、无暗烧、无重复），确认后再对用户开放。

---

## 十一、部署报告模板（Coze 部署后填写并输出 `STAGING_V4_FULL_DEPLOY_REPORT.md`）

```markdown
# STAGING V4 全量部署报告

- 后端 commit：<git rev-parse HEAD @ claude/v4-staging>
- 前端 commit：b0e0741（qoder/v4-frontend-workbench）
- DB 备份路径：/opt/v4-video-engine-staging/backend/meiye_v4_staging.db.bak.<TS>
- migration 结果：<migrate_staging.py 输出，列出 +新增 / =跳过 的列>
- backfill 结果：scanned=__ updated=__ unknown(NULL)=__
- .env 检查：ENABLE_COMPOSE=false ✅ / JWT_SECRET 未变 ✅ / UPLOAD_BASE_URL=https ✅ / VOLC_MODEL=__
- Nginx 检查：/api/→staging端口 ✅ / /static/videos/ ✅ / /static/uploads/ ✅ / client_max_body_size ✅ / 上传不 502 ✅
- A台 preview 测试：director_plan ✅ / image_roles ✅ / estimated_cost ✅ / 未调火山 ✅ / 未扣费 ✅
- A台 4031 测试：compose 锁态返回 4031 ✅ / 前端文案 ✅
- B台裂变测试：source_video_ids ✅ / batch_id ✅ / total_outputs=30 ✅ / viral 刷新 ✅ / cost=0 ✅
- 候选池测试：feedback→pending ✅ / super_admin 可见 ✅ / user 不可见 ✅
- Patch6 测试：/api/me ✅ / 发码 ✅
- production 零影响检查：未停 `v4-video-engine.service` ✅ / 未改 `/opt/v4-video-engine/backend/meiye_v4.db` ✅ / 未改 production nginx ✅ / `video.beautypeaceai.com` 健康 ✅ / 仅作用 `/opt/v4-video-engine-staging/` 与 `/opt/v4-video-engine/storage-staging/` ✅
- 是否可交吴哥手动验收：是 / 否（说明）
```
