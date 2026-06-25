# V4 页面重构 P1 · 技术设计 (L4)

> **本文件自包含**：面向未读过 V4 代码的模型（Qoder/Kimi/智谱）。不依赖「你已知」「如前所述」。
> 依据：仓库 `meiyewuge/-FASTAPI-BACKEND-` 分支 `claude/v4-staging`（FastAPI + SQLAlchemy 2.0 + SQLite，生产可切 PostgreSQL via `DATABASE_URL`）。
> 后端目录：仓库根下 `backend/`。统一响应壳 `{code,message,data}`；鉴权 `Authorization: Bearer <JWT(HS256)>`。

---

## 0. 现状速览（真实，勿臆测）

- 应用入口 `backend/main.py`；路由 `backend/api/routes.py`（前缀 `/api`）；建表 `Base.metadata.create_all`（启动自动建新表，**不自动给存量表加列**）。
- 鉴权依赖 `backend/api/deps.py`：
  - `get_current_user` → 从 JWT 取 `{tenant_id, phone, role}`，无/过期 → 401。
  - `get_tenant_id` → 基于 `get_current_user` 返回 `tenant_id`。
  - `require_invite_permission` → super_admin/invite_admin 或 `X-Admin-Key` 应急。
  - `require_super_admin` → 仅 super_admin。
- **A台 `/api/a/generate` 当前已是「登录即可（require_auth）」**，从来不是 require_super_admin。所谓「取消授权卡控」在后端无守卫需要改，仅前端去掉「联系管理员」文案。
- **B台 `/api/b/batch-generate` 当前已是 require_auth**，但**需要显式传 `sources` 数组**。P1 改为「可不传 sources，后端自动选源 + 1:10」。
- **`videos` 表当前没有 `duration` 字段** → 实现「源视频时长≥30s」过滤必须新增该列（本轮做）。
- B台引擎 `backend/b_engine/remixer.py` 已有 `ffprobe` 探测时长函数 `_probe_duration()`；A台多段拼接已有 `backend/services/compose_service.py` + `a_engine/video_composer.py`（一句话+总时长→切≤15s段→逐段生成→ffmpeg concat→母视频）。

---

## 1. 当前 staging DB 完整 schema（11 张表，CREATE TABLE 全量）

> SQLite 方言。PostgreSQL 差异：`INTEGER PRIMARY KEY AUTOINCREMENT` → `SERIAL/IDENTITY`；`DATETIME` → `TIMESTAMP`；`FLOAT` 通用。

```sql
-- 1) tenants 租户（含配额/订阅/试用）
CREATE TABLE tenants (
  id                  VARCHAR(64)  PRIMARY KEY,
  name                VARCHAR(128),
  quota               FLOAT        NOT NULL DEFAULT 100.0,
  subscription_status VARCHAR(16)  NOT NULL DEFAULT 'trial',  -- trial|active|expired
  trial_remaining     INTEGER      NOT NULL DEFAULT 3,
  created_at          DATETIME     DEFAULT CURRENT_TIMESTAMP
);

-- 2) stores 门店（租户内任务对象，非租户）
CREATE TABLE stores (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id  VARCHAR(64) NOT NULL DEFAULT 'default',
  name       VARCHAR(128) NOT NULL,
  city       VARCHAR(64),
  industry   VARCHAR(64),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_stores_tenant_id ON stores (tenant_id);

-- 3) videos 视频（母 mother / 裂变 viral 共用）
CREATE TABLE videos (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id       VARCHAR(64)  NOT NULL DEFAULT 'default',
  store_id        INTEGER,
  type            VARCHAR(16)  NOT NULL,                  -- mother|viral
  source_type     VARCHAR(16)  NOT NULL DEFAULT 'generated', -- generated|uploaded|remixed
  storage_status  VARCHAR(16)  NOT NULL DEFAULT 'active',  -- active|expired|deleted
  expires_at      DATETIME,
  origin_file_id  VARCHAR(40),
  parent_video_id INTEGER,
  batch_id        VARCHAR(40),
  thumbnail_path  VARCHAR(512),
  title           VARCHAR(255),
  strategy        VARCHAR(32),
  source_video_id INTEGER,
  status          VARCHAR(16)  NOT NULL DEFAULT 'ready',
  download_url    VARCHAR(512),
  cdn_url         VARCHAR(1024),
  local_url       VARCHAR(512),
  cover_url       VARCHAR(512),
  share_url       VARCHAR(512),
  volcano_task_id VARCHAR(64),
  meta            TEXT,
  created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_videos_tenant_id ON videos (tenant_id);
CREATE INDEX ix_videos_store_id  ON videos (store_id);
CREATE INDEX ix_videos_strategy  ON videos (strategy);
CREATE INDEX ix_videos_expires_at ON videos (expires_at);
CREATE INDEX ix_videos_batch_id  ON videos (batch_id);

-- 4) tasks 异步任务
CREATE TABLE tasks (
  id          VARCHAR(40) PRIMARY KEY,
  tenant_id   VARCHAR(64) NOT NULL DEFAULT 'default',
  store_id    INTEGER,
  type        VARCHAR(8)  NOT NULL,                 -- a|b|compose
  batch_id    VARCHAR(40),
  run_id      VARCHAR(40),
  status      VARCHAR(16) NOT NULL DEFAULT 'pending', -- pending|running|done|failed
  progress    FLOAT       NOT NULL DEFAULT 0.0,
  payload     TEXT,
  result      TEXT,
  error       TEXT,
  retry_count INTEGER     NOT NULL DEFAULT 0,
  created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_tasks_tenant_id ON tasks (tenant_id);
CREATE INDEX ix_tasks_store_id  ON tasks (store_id);
CREATE INDEX ix_tasks_batch_id  ON tasks (batch_id);
CREATE INDEX ix_tasks_run_id    ON tasks (run_id);

-- 5) cost_records 成本台账
CREATE TABLE cost_records (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id  VARCHAR(64) NOT NULL DEFAULT 'default',
  store_id   INTEGER,
  api_name   VARCHAR(64) NOT NULL,                 -- video.generate.a | video.remix.b
  provider   VARCHAR(64) NOT NULL DEFAULT '',      -- volcano_seedance|mock|local_ffmpeg
  task_id    VARCHAR(40),
  units      FLOAT NOT NULL DEFAULT 0.0,
  amount     FLOAT NOT NULL DEFAULT 0.0,
  duration   FLOAT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_cost_tenant_id ON cost_records (tenant_id);
CREATE INDEX ix_cost_store_id  ON cost_records (store_id);
CREATE INDEX ix_cost_task_id   ON cost_records (task_id);

-- 6) uploads 上传文件
CREATE TABLE uploads (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  file_id        VARCHAR(40) NOT NULL UNIQUE,
  tenant_id      VARCHAR(64) NOT NULL DEFAULT 'default',
  file_type      VARCHAR(16) NOT NULL,             -- image|text|video|file
  file_name      VARCHAR(255),
  file_size      INTEGER NOT NULL DEFAULT 0,
  local_path     VARCHAR(512),
  file_url       VARCHAR(512),
  storage_status VARCHAR(16) NOT NULL DEFAULT 'active',
  expires_at     DATETIME,
  created_at     DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_uploads_file_id   ON uploads (file_id);
CREATE INDEX ix_uploads_tenant_id ON uploads (tenant_id);
CREATE INDEX ix_uploads_expires_at ON uploads (expires_at);

-- 7) invite_codes 邀约码
CREATE TABLE invite_codes (
  code       VARCHAR(32) PRIMARY KEY,
  tenant_id  VARCHAR(64),
  phone      VARCHAR(32),
  active     BOOLEAN NOT NULL DEFAULT 1,
  max_uses   INTEGER NOT NULL DEFAULT 1,
  used_count INTEGER NOT NULL DEFAULT 0,
  note       VARCHAR(255),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 8) admin_users 管理员/角色
CREATE TABLE admin_users (
  phone      VARCHAR(32) PRIMARY KEY,
  role       VARCHAR(16) NOT NULL DEFAULT 'user',  -- super_admin|invite_admin|user
  status     VARCHAR(16) NOT NULL DEFAULT 'active',-- active|disabled
  created_by VARCHAR(32),
  note       VARCHAR(255),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 9) workflow_runs 工作流记录（回流层）
CREATE TABLE workflow_runs (
  run_id             VARCHAR(40) PRIMARY KEY,
  tenant_id          VARCHAR(64) NOT NULL,
  phone              VARCHAR(32),
  prompt             TEXT,
  mode               VARCHAR(16) NOT NULL,         -- a_generate|b_remix|batch
  input_image_count  INTEGER NOT NULL DEFAULT 0,
  input_file_count   INTEGER NOT NULL DEFAULT 0,
  input_video_count  INTEGER NOT NULL DEFAULT 0,
  input_text_length  INTEGER NOT NULL DEFAULT 0,
  source_video_count INTEGER NOT NULL DEFAULT 0,
  output_video_count INTEGER NOT NULL DEFAULT 0,
  cost_amount        FLOAT   NOT NULL DEFAULT 0.0,
  status             VARCHAR(16) NOT NULL DEFAULT 'running', -- running|done|failed
  error_message      TEXT,
  created_at         DATETIME DEFAULT CURRENT_TIMESTAMP,
  completed_at       DATETIME
);
CREATE INDEX ix_wfr_tenant_id ON workflow_runs (tenant_id);

-- 10) video_feedback_signals 行为信号（回流层）
CREATE TABLE video_feedback_signals (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id  VARCHAR(64) NOT NULL,
  phone      VARCHAR(32),
  video_id   INTEGER,
  action     VARCHAR(16) NOT NULL,  -- play|select|send_to_b|download|export|favorite|dislike|delete
  context    TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_vfs_tenant_id ON video_feedback_signals (tenant_id);
CREATE INDEX ix_vfs_video_id  ON video_feedback_signals (video_id);

-- 11) knowledge_candidates 知识候选池（回流层）
CREATE TABLE knowledge_candidates (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id       VARCHAR(64) NOT NULL,
  phone           VARCHAR(32),
  source_module   VARCHAR(16) NOT NULL DEFAULT 'video_v4',
  source_type     VARCHAR(24) NOT NULL,   -- prompt|script|strategy|workflow_summary|failure_case|user_feedback
  task_id         VARCHAR(40),
  batch_id        VARCHAR(40),
  video_id        INTEGER,
  title           VARCHAR(255),
  content_summary TEXT,
  tags            TEXT,
  raw_ref         VARCHAR(255),
  risk_level      VARCHAR(8)  NOT NULL DEFAULT 'low',
  status          VARCHAR(12) NOT NULL DEFAULT 'pending', -- pending|approved|rejected|archived
  created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  reviewed_at     DATETIME,
  reviewed_by     VARCHAR(32),
  review_note     VARCHAR(255)
);
CREATE INDEX ix_kc_tenant_id ON knowledge_candidates (tenant_id);
```

---

## 2. DB 变更（完整可执行 SQL + 回滚 + 迁移）

### P1-A: `videos` 增加 `duration`（本轮做，必需）
```sql
-- 原因：P1 B台门槛「源视频时长≥30s」需要后端可判断时长；当前 videos 无 duration 列。
-- 变更：
ALTER TABLE videos ADD COLUMN duration FLOAT;        -- 单位：秒；NULL=未知

-- 数据迁移（回填存量视频时长）：对 storage_status='active' 且本地文件存在的视频，
--   用 ffprobe 探测后 UPDATE。提供脚本 backend/tasks/backfill_duration.py（仅读文件，不调火山）。
--   伪：for v in active videos: d = ffprobe(local_path(v)); UPDATE videos SET duration=d WHERE id=v.id;

-- 回滚：
ALTER TABLE videos DROP COLUMN duration;   -- SQLite<3.35 不支持 DROP COLUMN，则重建表或保留空列即可
```

### P1-B 逻辑变更（无 schema 变更）
```sql
-- P1-1 裂变门槛：从「勾选N裂变N」改为「自动选源 + 1:10（30/40/50）」。
--   纯代码（orchestrator.submit_b_batch + 路由），无 schema 变更。回滚=恢复旧 submit_b_batch。
-- P1-8 A台权限：当前后端已是 require_auth（非 require_super_admin），无 schema/守卫变更。
--   仅前端去除「联系管理员」卡控 + 增加费用确认。回滚无需。
-- P1-5 A台一键成片：复用 compose_service（多段15s→concat），无 schema 变更。
-- P1-6 时长控制：remixer/composer 的 ffmpeg 参数调整，无 schema 变更（见 §7）。
```

### 迁移执行顺序（生产/staging）
1. 备份 DB 文件。
2. 执行 `ALTER TABLE videos ADD COLUMN duration FLOAT;`
3. 运行回填脚本 `python -m tasks.backfill_duration`（可选，存量少可跳过；新数据自动写 duration）。
4. 全新库无需任何 ALTER（`create_all` 建表即含 duration —— 模型已声明）。

> ⚠️ 回流层三表 `workflow_runs/video_feedback_signals/knowledge_candidates` 与 `tasks.run_id`、`videos` 既有 P0 列若生产尚未建，请先按 `BACKEND_V4_PAGE_REDESIGN_P0_REPORT.md` §三补齐，再做本 P1 的 `duration`。

---

## 3. API 完整规格（变更 + 关键现存）

### 3.1 `POST /api/b/batch-generate`（**P1 变更**：自动选源 + 1:10）
- **权限**：`require_auth`（登录即可，不卡管理员）。
- **请求体**：
  - `prompt`: string（必填，裂变需求描述）
  - `total_limit`: integer（选填；默认 = 合格源视频数 × 10，硬上限 50）
  - `sources`: array（**选填**；为空/省略则后端**自动选取**本租户合格源视频；传了则按传入源，兼容 P0）
- **自动选源规则**：`type=mother AND storage_status='active' AND duration>=30`，按 `created_at desc`。
- **响应 `data`**：
  - `batch_id`: string
  - `total_outputs`: integer（计划产出条数）
  - `source_count`: integer（实际参与的源视频数）
- **错误码**：`2001`（合格源视频<3 / sources 非法 / 超上限）；`401`（未登录）；`4029`（成本熔断，B台为0通常不触发）；`500`（裂变服务异常）。
- **前端触发**：点 B台按钮。**异步**：是（轮询 batch_id）。**花钱**：否（本地 ffmpeg，成本 0）。

### 3.2 `GET /api/b/batch/{batch_id}`（现存，不变）
- 权限 require_auth。响应 `{batch_id,status(queued|running|done|failed),total_outputs,completed,failed,video_ids[]}`。错误 `3001` 批次不存在/非本租户。

### 3.3 `POST /api/a/generate`（权限现状澄清；P1 新增 image 透传已在 P0 完成）
- **权限**：`require_auth`（**现状即如此**；无需从 require_super_admin 改）。
- 请求 `{prompt, title?, duration(4-15), resolution, image_file_id?}`；响应 `{task_id}`；轮询 `GET /api/tasks/{id}`。
- **会花钱**（火山）。配额/试用/订阅/cost_engine 保护**保留**：`ensure_budget` 熔断（4029）、Patch5 试用仅 A台扣减。
- **一句话批量** `POST /api/generate {text}`：超 `max_a_batch`(默认10) → 2001（防误触）。

### 3.4 `POST /api/compose`（现存，A台一键成片底座）
- 请求 `{prompt, total_seconds(5-180), resolution, title?}` → 切≤15s 多段 → 逐段火山生成 → ffmpeg concat → 母视频。响应 `{task_id}`。**会花钱**。P1 的「文字+图片→多段15s→拼接」直接复用本能力（见 §6）。

### 3.5 `POST /api/uploads/batch`（现存，P0）
- multipart：`files`(可重复，image/video/file)、`texts`(可重复)。返回 `{uploaded:[{file_id,file_name,file_type,file_size,file_url,thumbnail_url,status,video_id,zip_entries?}],failed:[{file_name,reason}]}`。video 自动登记为 `source_type=uploaded` 的 mother。**P1 待办**：上传 video 时同步用 ffprobe 写入 `videos.duration`（本轮做，见 §5）。

### 3.6 `GET /api/videos`（现存）
- 参数 `type=mother|viral|all`、`source_type`、`batch_id`、`store_id`、`source_video_id`、`strategy`、`page`、`page_size`、`sort=created_desc|created_asc`、`include_expired=false`。**P1 待办**：item 增加 `duration` 字段返回。

### 3.7 `DELETE /api/videos/{id}`（现存，P0 收口）
- user/invite_admin 仅删本租户（跨租户 403 不生效）；super_admin 删任意租户。soft delete（删文件 + storage_status=deleted）。

### 3.8 `GET /api/storage/status`（现存，P0 收口，分角色）
- user/invite_admin → `scope=tenant`（无全局磁盘）；super_admin → `scope=global`（磁盘 + tenant_summary）。

### 3.9 回流层（现存，P0）
- `POST /api/events/track {action,video_id?,context?}`（tenant/phone 取自 JWT；失败前端不阻断）。
- `POST /api/videos/{id}/feedback {rating(good|bad),tags,note}` → 候选 pending。
- `GET /api/admin/knowledge-candidates?status=`、`POST /.../{id}/approve|reject`（仅 super_admin；P1 仅置状态，不推大库）。

---

## 4. 权限调整对照表

| 端点 | 当前权限（真实代码） | P1 改后 | 原因 |
|----|----|----|----|
| `POST /api/a/generate` | `require_auth`（登录即可） | **不变**（保持 require_auth） | 邀请制已控入口；前端去掉「联系管理员」卡控 + 加费用确认即可，后端无守卫变更 |
| `POST /api/generate`（一句话A台） | `require_auth` | 不变 | 同上；保留 `max_a_batch` 防误触 |
| `POST /api/b/batch-generate` | `require_auth` | 不变（**逻辑变更**：自动选源 1:10） | 裂变不卡权限；门槛改为「源视频≥3且≥30s」业务校验 |
| `DELETE /api/videos/{id}` | require_auth + 租户隔离 + super 全局 | 不变 | P0 已收口 |
| `GET /api/storage/status` | require_auth + 角色 scope | 不变 | P0 已收口 |
| 候选池 `/api/admin/knowledge-candidates*` | `require_super_admin` | 不变 | 平台级审核 |

> 结论：**P1 无权限守卫层的破坏性变更**；A/B 台早已是登录即用。卡控的取消主要在前端文案与交互。

---

## 5. 上传写入时长（本轮做，配合 P1-A）

`backend/services/upload_service.register_uploaded_video()` 在落 `storage/mother/{id}.mp4` 后，增加：
```python
# 伪代码
dur = ffprobe_duration(final_path)   # 复用 remixer._probe_duration 同款 ffprobe
video.duration = dur
```
A台生成/compose 落库时同样写 `video.duration`（A台单段=duration 参数；compose=total_seconds）。

---

## 6. B台裂变新逻辑（伪代码，本轮做）

```python
# orchestrator.submit_b_batch（P1 改造）
def submit_b_batch(db, tenant_id, prompt, total_limit=None, sources=None, phone=None):
    # 1) 自动选源（sources 省略时）
    if not sources:
        cands = (db.query(Video)
                   .filter(Video.tenant_id==tenant_id,
                           Video.type=='mother',
                           Video.storage_status=='active',
                           Video.duration != None,
                           Video.duration >= 30)
                   .order_by(Video.created_at.desc()).all())
        # 2) 门槛
        if len(cands) < 3:
            raise ValueError("请至少上传3个时长30秒以上的视频")   # → 路由映射 2001
        # 3) 1:10，30/40/50 封顶
        per = 10
        cap = min(len(cands) * per, 50)
        sources = []
        remaining = cap
        for v in cands:
            if remaining <= 0: break
            take = min(per, remaining)
            sources.append({"source_video_id": v.id, "count": take, "strategy": "mix"})
            remaining -= take
    else:
        # 兼容 P0：显式 sources 仍走原校验（每源归属 + 总量≤total_limit≤50）
        ...
    # 4) 建批次 + run + 每源一个 b 任务（本地 ffmpeg，0 成本，不调火山）
    batch_id = uuid(); run_id = reflow.start_run(mode='batch', ...)
    for s in sources:
        ensure_budget(tenant_id, "video.remix.b", s["count"])   # B台价≈0
        create_task(type='b', payload={**s, "prompt":prompt, "batch_id":batch_id}, batch_id, run_id)
    return {"batch_id": batch_id, "total_outputs": sum(s["count"] for s in sources),
            "source_count": len(sources)}
```
- 路由 `ValueError → Resp(code=2001)`；前端据此弹「裂变门槛弹窗」。
- 单源裂变条数：每源 10；总封顶 50（5 源即满）。3→30、4→40、5+→50。

---

## 7. A台一键成片流程（伪代码，本轮以复用为主）

```python
# 复用 compose_service：文字(+参考图) → 多段15s → ffmpeg concat → 母视频
def one_click_compose(db, tenant_id, prompt, image_file_ids=None, total_seconds=45):
    n = ceil(total_seconds / 15)                  # 切 n 段，每段≤15s
    segs = []
    for i in range(n):
        seg_prompt = segment_prompt(prompt, i)    # 可结合参考图 image_file_ids
        seg = call_volcano(seg_prompt, duration=15, reference_images=image_file_ids)  # 会花钱
        segs.append(download(seg.url))
    final = ffmpeg_concat(segs)                    # 无损拼接
    video = save_mother(final, duration=total_seconds, source_type='generated')
    record_cost_per_segment(...)                   # cost_engine 逐段按秒计费
    return {video_id, duration: total_seconds, segments: n}
```
> 现状：`/api/compose` 已实现「prompt+total_seconds→多段→concat」。P1 增量 = 把参考图 `image_file_id` 透传进逐段生成（A台已支持 image_file_id 记录，真实图生视频待真实火山 key）。

---

## 8. ffmpeg 时长控制方案

```bash
# B台裂变：目标 90–120 秒混剪（P1-B：remixer 增加 -t 目标时长控制）
ffprobe -v error -show_entries format=duration -of csv=p=0 source.mp4   # 探测源时长
ffmpeg -y -ss <rand> -t 30 -i source.mp4 -c copy clipN.mp4             # 多段随机截取
printf "file 'clip1.mp4'\nfile 'clip2.mp4'\n..." > list.txt
ffmpeg -y -f concat -safe 0 -i list.txt -t ${TARGET_DURATION} -c copy out.mp4  # 拼接到目标(90-120)

# A台拼接：多段 15 秒无损合成
printf "file 'seg0.mp4'\n..." > segments.txt
ffmpeg -y -f concat -safe 0 -i segments.txt -c copy final_mother.mp4
```
- 现状 remixer：切片 + 文案 drawtext（CJK 字体 `/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc`），已有 `_probe_duration`。P1-B 增加目标时长 `-t` 控制裂变成片 90–120s。
- 字体缺失/编码失败有 `-c copy` 兜底（已实现）。

---

## 9. 素材库预留接口（P2，仅占位不实现）
```
GET  /api/stock-library/search?q=&type=image|video&free=true&price_max=0
GET  /api/stock-library/{id}/preview
POST /api/stock-library/{id}/download   → 自动加入项目素材（写 uploads + 可登记 video）
```
> 标注 **P2**：当前仅文档占位，不建表、不实现路由。未来对接版权素材源。

---

## 10. 部署清单（扣子照走；本轮文档不部署）
```
Step 1  备份 staging：backend 目录 + 前端 dist + DB 文件（meiye_v4_staging.db.bak.<ts>）
Step 2  git fetch && git checkout claude/v4-staging && git pull
Step 3  恢复 .env（不覆盖 JWT_SECRET / ADMIN_KEY / VIDEO_API_KEY）
Step 4  执行 DB migration：ALTER TABLE videos ADD COLUMN duration FLOAT;（+ 可选回填脚本）
Step 5  重启 staging 后端：systemctl restart v4-video-engine-staging
Step 6  验证后端：curl http://127.0.0.1:<port>/health；抽测 /api/b/batch-generate 自动选源
Step 7  拉取 Qoder 前端最新 commit
Step 8  npm ci && npm run build
Step 9  部署 dist 到 staging 前端目录
Step 10 reload staging Nginx
Step 11 全链路验证（上传→A台→母视频面→B台自动裂变→裂变面→下载→反馈→候选池）
Step 12 输出部署报告
```

## 11. 回滚方案
```
1. 恢复后端：cp -r backend.bak.<ts>/* backend/
2. 恢复 DB：cp meiye_v4_staging.db.bak.<ts> meiye_v4_staging.db
   （或仅回滚列：SQLite 保留空 duration 列即可，不影响旧逻辑）
3. 重启：systemctl restart v4-video-engine-staging
4. 验证：curl http://127.0.0.1:<port>/health
5. 前端回滚：部署上一个 dist 备份 + reload Nginx
```

---

## 12. 范围划分：本轮 / P1-B / P2

| 项 | 归属 | 说明 |
|----|----|----|
| `videos.duration` 列 + 上传/生成写时长 + 回填脚本 | **本轮** | B台门槛与展示所需 |
| B台自动选源 + 1:10（30/40/50） + 门槛 400/2001 | **本轮** | `submit_b_batch` 改造 + 路由 |
| `/api/videos` 与列表 item 返回 `duration` | **本轮** | 前端显示时长、判断门槛 |
| 前端删文本入口/蓝色按钮、A台费用确认、取消勾选 | **本轮（前端）** | 纯前端，后端无改 |
| A台一句话/compose 复用为「一键成片」 | **本轮（复用）** | 底座已具备 |
| B台裂变成片目标 90–120s（ffmpeg `-t`） | **P1-B** | remixer 引擎参数调整，可紧随本轮 |
| A台参考图真正图生视频（image_file_id→provider） | **P1-B** | 待真实火山 key 联调 |
| zip 深度解析、rar、大文件/OSS 迁移 | **P2** | 见 P0 报告未决项 |
| 素材库 `/api/stock-library/*` | **P2** | 仅占位 |
| 回流 approved → 阿里云大库单向导出器 | **P2** | P0/P1 仅进候选池，不推大库 |

---

## 13. 重点业务规则（汇总，给实现模型对齐）
- B台裂变**至少 3 个源视频**；建议每个源视频 **≥30 秒**（<30s 不计入合格源）。
- **3 源→30 条；4 源→40 条；5 源及以上→最多 50 条**（每源 1:10，总封顶 50）。
- 前端**主流程不再勾选确认**；点 B台即按自动选源裂变。
- A台**取消「联系管理员」卡控**，改为**登录用户可用 + 费用提醒确认弹窗**。
- A台**仍保留余额/试用/订阅/cost_engine 保护**（熔断 4029、试用仅 A台扣减）。
- A台目标：**文字 + 图片 → 多段 15 秒 → 后端自动拼接 → 成型母视频**。
- 裂变结果**必须进入裂变视频陈列面**（`type=viral`，0 元标签）。
- 视频与素材**仍走临时存储策略**（裂变 5 天 / 上传 7 天 / 母视频默认长期可手删；到期自动清理）。
- 业务回流**只进候选池（pending）**，**不直接进阿里云正式大库**（审核后 P2 导出）。
