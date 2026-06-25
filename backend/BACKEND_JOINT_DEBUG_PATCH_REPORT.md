# 后端联调补丁报告（BACKEND_JOINT_DEBUG_PATCH_REPORT）

> 范围：**后端 only**（不碰前端 / Qoder，不碰部署）。
> 开发分支：`claude/v4-staging`（基于 B9 冻结，**不直接改生产** `ecs-production-snapshot`）。
> 每个补丁独立 commit，可单独回滚。

| 补丁 | commit | 主题 |
|----|--------|------|
| Patch1 | `dd39560` | staging 建立 + B9 确认（B台本地 ffmpeg 裂变 / 0 成本 / 不调火山） |
| Patch2 | `36cf4e8` | 上传接口 `POST /api/upload`（image/text/video） |
| Patch3 | `dd1264b` | 导出修复（方案B）：保留 CSV 元数据，新增视频 URL 导出 |
| Patch4 | `107185e` | 访问卡控第一阶段：邀约码 + JWT 鉴权 |
| Patch5 | `0017995` | 订阅/试用字段（暂不接支付） |

合计：20 files changed, 826 insertions(+), 24 deletions(-)。

---

## Patch1 — B9 合并与确认

**做了什么**：确认 staging 已含 B9（`e41fd1d` 为当前分支祖先），并加可重复回归测试固化 B台 = 纯本地 ffmpeg。

**改动文件**
- `tests/test_b9_local_remix.py`（新增）：母视频 → B台裂变 3 条 → 本地 mp4 落盘可播放可下载；断言 `cost=0`、`provider=local_ffmpeg`、`remixer` 源码中无 `get_provider`（即不引入任何 provider）。

**已验证**
- B台不调用火山 API，成本记录 `amount=0.0 / provider=local_ffmpeg`。
- 链路：母视频 → B台裂变 → viral mp4 落盘 → `download_url` 指向本地 `/viral/{id}.mp4`（非 mock.cdn）→ 文件存在且 size>0。

**前端无新增对接**（B台接口不变）。

---

## Patch2 — 上传接口 `POST /api/upload`

**新增 API**：`POST /api/upload`（`multipart/form-data`）

| 字段 | 说明 |
|----|----|
| `type` | `image` / `text` / `video`（必填，Form） |
| `file` | 文件（image/video 用；File） |
| `content` | 文本内容（type=text 用；Form） |

约束：image `jpg/png/webp ≤10MB`；video `mp4/mov/avi ≤500MB`；text 脚本/文案。
返回：`{file_id, file_url, file_type, file_size, local_path}`。

**改动文件**
- `models/upload.py`（新增）：`uploads` 表（file_id 唯一、tenant_id、file_type、file_name、file_size、local_path、file_url、created_at）。
- `utils/upload_util.py`（新增）：`safe_name()` 去危险字符 + 去路径成分；`validate()` 扩展名白名单 + MIME 魔数 + 大小上限；`save()` uuid 文件名落盘（杜绝路径穿越）。
- `services/upload_service.py`（新增）：校验 → 落盘 → 入库 → 返回。
- `api/routes.py`：新增 `/upload` 端点。
- `config.py`：`upload_dir` / `upload_base_url` / `max_image_mb=10` / `max_video_mb=500`。
- `requirements.txt`：`python-multipart>=0.0.9`。

**落盘目录**：`{upload_dir}/images|texts|videos/{uuid}.{ext}`。

**安全**：文件名 uuid 化（无穿越）、MIME 魔数校验（jpg/png/webp/mp4/mov/avi 头部字节）、大小上限、扩展名白名单。

**前端如何调用**：`FormData` 带 `type` + `file`（或 `content`），`Authorization: Bearer <JWT>`；用返回的 `file_url`（已配 `upload_base_url`/nginx 时）或 `local_path`。

---

## Patch3 — 导出修复（方案B）

**保留**：`POST /api/export` 的 CSV/JSON 元数据导出**不变**。

**新增 API**：`POST /api/export/videos` → 返回选中视频的 mp4 下载 URL 列表
`{count, videos:[{video_id, type, title, download_url, cover_url}]}`，前端逐条下载。

**改动文件**
- `api/routes.py`：新增 `/export/videos`（复用 `export_service.select_videos` 的筛选）。

**入参**（同 `ExportIn`）：`video_ids` 或筛选条件（`type/strategy/store_id/source_video_id`）。

**留待下一阶段**：ZIP 批量打包。

**前端如何调用**：勾选视频 → `POST /api/export/videos` → 拿 `download_url` 列表逐条触发下载；CSV 仍走 `POST /api/export {format:"csv"}`。

---

## Patch4 — 访问卡控第一阶段：邀约码 + JWT

**替换**：原 auth stub（`tk_<tenant>` 占位）已删除，改为真实 JWT 鉴权。

**新增表**：`invite_codes`（`code` 主键 / `tenant_id` 可空 / `active` / `max_uses` / `used_count` / `note` / `created_at`）。

**鉴权流程**
1. 管理员生成邀约码。
2. 登录 = **手机号 + 邀约码**（`POST /api/auth/login {phone, invite_code}`）。无邀约码（schema 必填 → 422）/ 无效 / 用尽 → 拒绝（`code:1002`）。
3. 登录成功签发 **JWT（HS256，标准库实现，无 PyJWT 依赖）**，payload 含 `tenant_id/phone/iat/exp`。
4. **所有业务 API 从 `Authorization: Bearer <JWT>` 解析 `tenant_id`**；无 token / 过期 / 篡改 → **401**（统一 `{code:1001, message, data:null}`）。

**新增/最小管理员端点**（`X-Admin-Key` 守卫，`config.admin_key` 为空则禁用 → 403）
- `POST /api/admin/invite/generate {count, tenant_id?, max_uses, note?}`
- `GET /api/admin/invite/list`
- `POST /api/admin/invite/revoke {code}`

**改动文件**
- `utils/jwt_util.py`（新增）：HS256 `encode/decode` + 过期校验。
- `models/invite.py`（新增）+ `models/__init__.py`（注册 InviteCode）。
- `services/invite_service.py`（新增）：`generate/list_codes/revoke/validate_and_consume`。
- `api/deps.py`：`get_tenant_id` 改为解析 Bearer JWT（401）；新增 `require_admin`。
- `api/routes.py`：登录改写 + 3 个管理员端点。
- `schemas/dto.py`：`LoginIn{phone, invite_code}` + `InviteGenIn` + `InviteRevokeIn`。
- `main.py`：新增 `StarletteHTTPException` 处理器，401/403 → `{code:1001}`。
- `config.py`：`jwt_ttl_seconds`（默认 7 天）、`admin_key`、`auth_required`（默认 True）。

**已验证**（`tests/verify_patch4.py`）：无 JWT→401、管理端点缺 key→401、生成邀约码、无/无效/用尽邀约码拒绝登录、登录签发 JWT、带 JWT 放行、作废后登录失败、篡改/过期 token→401、查看列表。

**前端如何调用**
- 登录：`POST /api/auth/login {phone, invite_code}` → 存 `data.token`。
- 其后所有请求带 `Authorization: Bearer <token>`；收到 401 即跳登录。
- 管理后台（如有）：带 `X-Admin-Key` 调 `/api/admin/invite/*`。

---

## Patch5 — 订阅/试用字段（暂不接支付）

**新增字段**（`tenants` 表）
- `subscription_status`：`trial` / `active` / `expired`（默认 `trial`）。
- `trial_remaining`：试用余量（默认 3）。

**新增 API**：`GET /api/subscription/status` → `{status, trial_remaining, quota_remaining}`
（`quota_remaining = quota - 已花成本`）。

**试用扣减口径**：**仅 A台（母视频生成）扣减，B台裂变不扣**。
- `orchestrator.submit_a`：每次 A台生成扣 1。
- `orchestrator.plan_from_intent`：每条母视频扣 1。
- `orchestrator.submit_b`（B台）：**不扣**。
- 扣到 0 不为负；当前阶段**不做硬熔断**（无支付），放行与否仍由成本配额（cost_engine）决定。

**改动文件**
- `models/tenant.py`：新增 `subscription_status` / `trial_remaining`。
- `services/subscription_service.py`（新增）：`get_status` / `consume_trial`（提交以释放 SQLite 写锁）。
- `services/orchestrator.py`：A台投递处接 `consume_trial`。
- `api/routes.py`：新增 `/subscription/status`。

**已验证**（`tests/verify_patch5.py`）：初始 trial=3、A台生成扣 1、B台裂变不扣、连续 A台耗尽至 0 不为负。

**前端如何调用**：`GET /api/subscription/status`（带 JWT）展示「试用剩余 N 次 / 配额余额」。

---

## 新增数据库迁移（DB migrations）

当前用 `Base.metadata.create_all`（启动建表），**新增表会自动建**：
- `invite_codes`（Patch4，新表 → 自动建）。
- `uploads`（Patch2，新表 → 自动建）。

**需手工迁移的存量表新增列**（`create_all` 不会给已存在的表加列）：
- `tenants` 新增 `subscription_status VARCHAR(16) NOT NULL DEFAULT 'trial'`、`trial_remaining INTEGER NOT NULL DEFAULT 3`（Patch5）。

> ⚠️ 生产 ECS 若 `tenants` 表已存在，需执行（联调/部署阶段，由运维执行，**本补丁不碰部署**）：
> ```sql
> ALTER TABLE tenants ADD COLUMN subscription_status VARCHAR(16) NOT NULL DEFAULT 'trial';
> ALTER TABLE tenants ADD COLUMN trial_remaining INTEGER NOT NULL DEFAULT 3;
> ```
> 全新库或测试库无需手动操作（建表即含新列）。

---

## 新增/变更环境变量（.env）

| 变量 | 默认 | 用途 |
|----|----|----|
| `JWT_SECRET` | `change_me` | **生产必须改**，JWT 签名密钥 |
| `JWT_TTL_SECONDS` | `604800`(7天) | token 有效期 |
| `ADMIN_KEY` | 空 | 管理端点口令；**空=禁用** `/api/admin/*` |
| `AUTH_REQUIRED` | `true` | 业务 API 是否强制 JWT |
| `UPLOAD_DIR` | `/opt/v4-video-engine/uploads` | 上传落盘根目录 |
| `UPLOAD_BASE_URL` | 空 | nginx 静态访问基址（生成 file_url） |
| `MAX_IMAGE_MB` / `MAX_VIDEO_MB` | 10 / 500 | 上传大小上限 |

依赖新增：`python-multipart>=0.0.9`（上传必需）。

---

## 已验证清单

- ✅ `tests/test_b9_local_remix.py`：B台本地裂变 / 0 成本 / 不调火山。
- ✅ `tests/test_volcano_pipeline.py`：A台/B台/任务/mock 回退/成本/AK-SK 签名（已适配 JWT 默认头）全过。
- ✅ `tests/verify_patch4.py`：邀约码 + JWT 全场景。
- ✅ `tests/verify_patch5.py`：试用扣减（A台扣/B台不扣/不为负）。
- 验证环境：本地 sandbox + 真实 ffmpeg + httpx 桩（**无真实火山 key**）。

---

## 未解决风险 / 注意事项

1. **生产 `tenants` 加列需手工 ALTER**（见迁移段）。`create_all` 不改存量表结构。
2. **JWT_SECRET / ADMIN_KEY 必须在生产 .env 配置**：`change_me` 默认值不可上线；`ADMIN_KEY` 不配则管理端点全禁用（403）。
3. **JWT 无刷新/吊销机制**：当前 token 在 `exp` 前一直有效，无黑名单。如需「踢下线」需后续加 token 版本号或服务端会话表。
4. **邀约码 `used_count` 并发**：高并发下 SQLite 行级竞争可能超发；生产 PostgreSQL + 行锁可规避，当前阶段未加锁。
5. **试用不做硬熔断**：`trial_remaining=0` 仍放行（无支付系统），仅成本配额 `cost_engine` 兜底。硬卡控待支付阶段决策。
6. **未接支付**：`subscription_status` 仅有字段与展示，无升级/续费/到期流转逻辑。
7. **上传未做杀毒/转码**：仅 MIME 魔数 + 大小 + 扩展名校验；如需深度内容校验/转码需另立任务。
8. **ZIP 批量导出未做**（Patch3 方案B 仅返回 URL 列表，前端逐条下载）。
9. **本报告不涉及部署**：ECS 上线（迁移、.env、重启）由运维/团队执行，本补丁仅交付后端代码与验证脚本。
