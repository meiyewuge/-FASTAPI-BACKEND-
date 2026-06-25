# 后端 V4 页面重构 P0 报告（BACKEND_V4_PAGE_REDESIGN_P0_REPORT）

> 范围：**后端 only**（不碰前端 / 不部署 / 不碰生产 / 不真实压测火山 / 不大文件压测 / 不泄露密钥）。
> 基于 `claude/v4-staging` 续做。目标：支撑「单一操作对话框 + 母视频/源视频陈列面 + 裂变视频陈列面」工作流。
> **Patch6 权限体系保持不变**（JWT 登录 / `/api/me` / super_admin·invite_admin·user / 发码权限均未改）。

| 项 | 值 |
|----|----|
| **commit** | `7184bbd`（`V4 page redesign P0: 批量上传/上传视频进陈列面/批量裂变/临时存储与自动清理`） |
| 分支 | `claude/v4-staging`（已推送 origin） |
| 测试 | `tests/verify_v4_p0.py` 13 项全过 + 全量回归通过 |

---

## 一、修改 / 新增文件

| 文件 | 变更 |
|----|----|
| `models/video.py` | 新增 `source_type / storage_status / expires_at / origin_file_id / parent_video_id / batch_id / thumbnail_path` |
| `models/upload.py` | 新增 `storage_status / expires_at` |
| `models/task.py` | 新增 `batch_id` |
| `utils/upload_util.py` | 新增 `file` 类别(doc/docx/zip)、`category_of()` 扩展名分流、doc/docx/zip 魔数校验、`inspect_zip()` zip bomb 防护 |
| `services/upload_service.py` | 新增 `handle_batch()`、`register_uploaded_video()`；单文件上传也登记视频 |
| `services/b_service.py` | viral 写入 source_type/expires_at/batch_id/parent_video_id；新增 `batch_status()` |
| `services/orchestrator.py` | 新增 `submit_b_batch()`；`submit_a()` 支持 image_file_id；`plan_from_intent()` A台防误触上限 |
| `services/storage_service.py`（新增） | `delete_video / storage_status / run_cleanup` |
| `services/a_service.py` | 记录 image_file_id 到母视频 meta（不改火山调用） |
| `tasks/video_task.py` | `create_task()` 支持 batch_id |
| `tasks/cleanup.py`（新增） | 清理 CLI 入口（systemd timer / cron） |
| `schemas/dto.py` | `BatchGenerateIn / BatchSourceIn`；`AGenerateIn.image_file_id` |
| `api/routes.py` | 新增 `/uploads/batch`、`/b/batch-generate`、`/b/batch/{id}`、`DELETE /videos/{id}`、`/storage/status`；升级 `/videos` |
| `config.py` | 批量/文档/zip/保留天数/批次上限等配置项 |
| `tests/verify_v4_p0.py`（新增） | 13 项端到端验证 |

---

## 二、新增接口

### 1. 批量上传 `POST /api/uploads/batch`（multipart/form-data，需 JWT）
- 字段：`files`（可重复，混合 image/video/file）、`texts`（可重复，文本内容）。
- 按扩展名自动分流：image(jpg/png/webp)、video(mp4/mov/avi)、file(doc/docx/zip)。
- 限制：每类 ≤10 个；image ≤10MB、video ≤500MB、file ≤50MB；单批总量 ≤2GB。
- **video 自动登记**为 `source_type=uploaded` 的母/源视频（落 `storage/mother/{id}.mp4`，抽封面，可被 B台裂变）。
- 返回：
```json
{ "uploaded": [ {"file_id","file_name","file_type","file_size","file_url","thumbnail_url","status","video_id","zip_entries?"} ],
  "failed":   [ {"file_name","reason"} ] }
```

### 2. 批量裂变 `POST /api/b/batch-generate`（需 JWT）
```json
{ "sources":[{"source_video_id":11,"count":5,"strategy":"mix"},{"source_video_id":12,"count":5}],
  "prompt":"抗衰主题", "total_limit":50 }
```
- 多源各设 count；**本地 ffmpeg、0 成本、不调火山**；总产出硬上限 50（P0）。
- 异步执行，返回 `{batch_id, total_outputs}`。

### 3. 批量进度 `GET /api/b/batch/{batch_id}`（需 JWT）
```json
{ "batch_id":"...", "status":"queued|running|done|failed",
  "total_outputs":50, "completed":20, "failed":0, "video_ids":[41,42,43] }
```

### 4. 列表升级 `GET /api/videos`（需 JWT）
新增参数：`type=mother|viral|all`、`source_type=generated|uploaded|remixed`、`batch_id`、`sort=created_desc|created_asc`、`include_expired=false`、`page/page_size`。
- 母/源视频陈列面：`GET /api/videos?type=mother&page=1&page_size=50`
- 裂变视频陈列面：`GET /api/videos?type=viral&page=1&page_size=50`
- 返回每条含 `source_type/storage_status/expires_at/parent_video_id/batch_id/thumbnail_url`。

### 5. 删除 `DELETE /api/videos/{id}`（需 JWT，tenant 隔离）
删服务器文件（mp4 + 封面），**保留 DB 记录**，`storage_status=deleted`。

### 6. 存储状态 `GET /api/storage/status`（需 JWT）
```json
{ "disk_total_gb":40, "disk_used_gb":12, "disk_used_percent":30,
  "mother_count":40, "viral_count":120, "upload_count":18 }
```
磁盘全局；数量按本租户 active 统计。

### 7. A台增强 `POST /api/a/generate`
新增可选 `image_file_id`（来自 `/api/upload` 的 file_id），记录到母视频 meta。**防误触**：`/api/generate`（一句话）生成母视频数超 `max_a_batch`（默认 10）→ `code:2001` 拒绝。

---

## 三、数据库 migration

`Base.metadata.create_all` 自动建新表；**存量表新增列需手工 ALTER**（生产已存在这些表时）：

```sql
-- videos
ALTER TABLE videos ADD COLUMN source_type VARCHAR(16) NOT NULL DEFAULT 'generated';
ALTER TABLE videos ADD COLUMN storage_status VARCHAR(16) NOT NULL DEFAULT 'active';
ALTER TABLE videos ADD COLUMN expires_at DATETIME;
ALTER TABLE videos ADD COLUMN origin_file_id VARCHAR(40);
ALTER TABLE videos ADD COLUMN parent_video_id INTEGER;
ALTER TABLE videos ADD COLUMN batch_id VARCHAR(40);
ALTER TABLE videos ADD COLUMN thumbnail_path VARCHAR(512);
-- uploads
ALTER TABLE uploads ADD COLUMN storage_status VARCHAR(16) NOT NULL DEFAULT 'active';
ALTER TABLE uploads ADD COLUMN expires_at DATETIME;
-- tasks
ALTER TABLE tasks ADD COLUMN batch_id VARCHAR(40);
```
> 全新库 / 测试库无需手工操作（建表即含新列）。SQLite 与 PostgreSQL 语法基本一致；PostgreSQL 可加 `CREATE INDEX` 于 batch_id/expires_at（模型已声明 index，全新建表自带）。

---

## 四、存储目录

| 用途 | 目录 |
|----|----|
| A台母视频 / 上传视频（源） | `{STORAGE_DIR}/mother/{video_id}.mp4`（+ `.jpg` 封面） |
| B台裂变视频 | `{STORAGE_DIR}/viral/{video_id}.mp4`（+ `.jpg` 封面） |
| 上传图片 | `{UPLOAD_DIR}/images/` |
| 上传文档(doc/docx/zip) | `{UPLOAD_DIR}/files/` |
| 上传文本 | `{UPLOAD_DIR}/texts/` |
| 上传视频原件 | `{UPLOAD_DIR}/videos/` |

> 落盘均用 uuid / 自增 id 文件名，杜绝路径穿越。

---

## 五、自动清理方案

| 类型 | 保留 | 到期动作 |
|----|----|----|
| B台裂变视频 | 5 天（`viral_retention_days`） | 删文件，`storage_status=expired`（**保留 DB 记录**，页面显示「已过期」） |
| 上传素材（图片/文档/视频/文本） | 7 天（`upload_retention_days`） | 同上 |
| A台母视频 | 默认长期（`mother_retention_days=0` → `expires_at=NULL`） | 不自动清，可手动 `DELETE` |
| 用户选中成片 | 用户本地电脑 | 浏览器下载，永久（服务器不负责） |

**执行**：`services/storage_service.run_cleanup()`，CLI 入口 `python -m tasks.cleanup`。建议由 **systemd timer / cron 每日**调用（**由 Coze 部署，本补丁不部署**）。示例：
```ini
# /etc/systemd/system/v4-cleanup.service
[Service]
WorkingDirectory=/opt/v4-video-engine/backend
ExecStart=/usr/bin/python -m tasks.cleanup
# /etc/systemd/system/v4-cleanup.timer
[Timer]
OnCalendar=*-*-* 04:00:00
Persistent=true
```
> 后续正式版可把大文件迁 **阿里云 OSS + 生命周期规则**（OSS 自动 5 天清理），ECS 只留 DB 记录与任务状态 —— 接口与字段已为此预留（`expires_at/storage_status/local_url`）。

---

## 六、测试结果（`tests/verify_v4_p0.py`，13/13 ✅）

```
✔ 批量上传 3 视频成功 → 进入母/源视频陈列面（source_type=uploaded）
✔ 批量上传 3 图片成功
✔ docx/zip 上传成功（zip 列出条目）；非法文件(exe/魔数不符)被拒
✔ 批量裂变 2 源各 1 条 → batch done, completed=2
✔ 裂变结果进入裂变视频陈列面（source_type=remixed）
✔ B台批量裂变成本 = 0（local_ffmpeg）
✔ expires_at 已写入（viral / uploaded 均临时保留）
✔ 删除视频删服务器文件并标记 deleted（DB 记录保留）
✔ /api/storage/status 正常（mother/viral/upload 计数）
✔ 租户隔离：B 看不到/删不掉 A 的文件
✔ 自动清理：过期文件删除 + 标记 expired
✔ Patch6 权限体系不受影响（登录带 role、/api/me 正常）
✔ A台防误触：一句话超额批量生成被拒（2001）
```
回归：`test_volcano_pipeline / test_b9_local_remix / verify_patch4 / verify_patch4_1 / verify_patch5 / verify_patch6_admin_roles` 全过。
验证环境：本地 sandbox + 真实 ffmpeg + 小样本（**无真实火山 key，无大文件压测**）。

---

## 七、是否影响 Patch6 权限

**不影响。** 所有新接口沿用 `get_tenant_id`（JWT）做租户隔离；未改 `admin_users` / 角色 / 发码端点 / bootstrap。`verify_v4_p0` 第 12 项专门复验：bootstrap + 登录签发带 role 的 JWT + `/api/me` 正常。

> 注：本轮新接口（批量上传/批量裂变/列表/删除/存储状态）按业务定位面向**登录用户**（JWT 即可），未加管理员门槛；如需把「删除/存储状态」收敛为管理员能力，可在 P1 用 `require_invite_permission`/`require_super_admin` 加守卫。

---

## 八、是否可交 Qoder 前端联调

**可以。** 三块工作流后端齐备：
- 操作框：`/api/uploads/batch`（上传）→ `/api/a/generate`（A台）/`/api/b/batch-generate`（B台批量）。
- 母视频/源视频陈列面：`GET /api/videos?type=mother`（含 generated + uploaded）。
- 裂变视频陈列面：`GET /api/videos?type=viral`（+ `batch_id` 看某批次）。
- 挑选/播放/下载：列表返回 `download_url/cover_url/thumbnail_url`；批量下载 URL 列表沿用 `POST /api/export/videos`。
- 进度：`GET /api/b/batch/{batch_id}`。
- 删除/容量：`DELETE /api/videos/{id}`、`GET /api/storage/status`。

**联调注意**
1. 生产存量表需按「三、migration」补列后再联调。
2. 所有接口带 `Authorization: Bearer <JWT>`。
3. 清理 timer 由 Coze 部署；未部署前到期文件不会自动清，但 `expires_at` 已正确写入。

---

## 九、未决 / P1

1. zip **深度解析**（解出内部文件入库）留 P1；P0 仅「存储 + 列条目」。
2. `rar` 暂缓（需服务器安全解压能力）。
3. 大文件 / OSS 迁移留 P1（字段已预留）。
4. 删除/存储状态是否收敛为管理员能力，待产品确认。
5. A台真实火山联调与图生视频（image_file_id 透传到 provider）留待真实 key 环境，本轮仅记录不压测。
