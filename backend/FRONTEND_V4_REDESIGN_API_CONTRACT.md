# 前端联调接口合同（FRONTEND_V4_REDESIGN_API_CONTRACT）

> 面向 Qoder 前端「单操作框 + 母视频/源视频陈列面 + 裂变视频陈列面」工作流。
> 后端分支 `claude/v4-staging`。**所有接口（除登录）都要带 `Authorization: Bearer <JWT>`**。
> 统一返回壳：`{ "code": 0, "message": "ok", "data": {...} }`，`code==0` 成功；非 0 见各接口错误码。
> 鉴权失败统一 `HTTP 401/403` + `{code:1001}`。参数校验失败 `HTTP 422` + `{code:2001}`。

## 通用约定
- Header：`Authorization: Bearer <JWT>`；JSON 接口 `Content-Type: application/json`；上传用 `multipart/form-data`。
- **tenant_id / phone 一律由后端从 JWT 解析**，前端不要传、传了也不信任。
- 角色：登录返回 `role`（`super_admin|invite_admin|user`），前端用 `/api/me` 控制管理员入口。
- 金额：**只有 A台（母视频生成）花钱（火山）**；B台裂变、上传、列表、删除、埋点、反馈**全部 0 成本**。

---

## 1) `POST /api/uploads/batch` —— 批量上传（操作框）
- **方法/Header**：POST，`multipart/form-data` + Bearer。
- **请求**：`files`（可重复，混合 image/video/file）；`texts`（可重复，文本内容）。
  - image：jpg/png/webp ≤10MB；video：mp4/mov/avi ≤500MB；file：doc/docx/zip ≤50MB；每类 ≤10 个；单批总量 ≤2GB。
- **返回 `data`**：
```json
{ "uploaded": [ {"file_id","file_name","file_type","file_size","file_url","thumbnail_url","status","video_id","zip_entries?"} ],
  "failed":   [ {"file_name","reason"} ] }
```
- **错误码**：单个文件失败进 `failed[]`（不整体失败）；超总量 → `failed:[{"*","单批总量超过上限"}]`。
- **前端场景**：操作框「上传素材」。**上传 video → 返回含 `video_id`，会自动出现在母视频/源视频陈列面**（`type=mother&source_type=uploaded`）。
- **异步**：否（同步返回）。**轮询**：否。**花钱**：否。**进候选池**：否。
- **失败是否阻断**：单文件失败只提示该文件，不阻断其余。

## 2) `GET /api/videos?type=mother` —— 母视频/源视频陈列面
- **方法/Header**：GET + Bearer。
- **请求参数**：`type=mother`、`source_type=generated|uploaded`（可选）、`page`、`page_size`、`sort=created_desc|created_asc`、`include_expired=false`、`store_id?`、`batch_id?`。
- **返回 `data`**：`{ "items":[ {video_id,type,source_type,storage_status,expires_at,title,strategy,store_id,source_video_id,parent_video_id,batch_id,download_url,share_url,cover_url,thumbnail_url} ], "total":N }`。
- **前端场景**：中部陈列面。`source_type=generated`=A台生成，`uploaded`=用户上传源视频。用 `thumbnail_url` 显示封面，`download_url` 播放/下载。
- **异步**：否。**轮询**：否。**花钱**：否。

## 3) `GET /api/videos?type=viral` —— 裂变视频陈列面
- 同上，`type=viral`。可加 `batch_id` 只看某次批量裂变结果、`strategy` 按策略筛。
- **前端场景**：下部陈列面。勾选满意的 → 下载到本地 / 反馈。
- **异步**：否。**轮询**：否。**花钱**：否。

## 4) `POST /api/b/batch-generate` —— 多源批量裂变（B台，0 成本）
- **方法/Header**：POST JSON + Bearer。
- **请求体**：
```json
{ "sources":[ {"source_video_id":11,"count":5,"strategy":"mix"}, {"source_video_id":12,"count":5} ],
  "prompt":"抗衰主题", "total_limit":50 }
```
  - 多源各设 `count`；总产出 ≤ `total_limit`（且硬上限 50）。
- **返回 `data`**：`{ "batch_id":"...", "total_outputs":10 }`。
- **错误码**：`2001`（sources 空 / 总量超上限 / 源视频不存在或非本租户）；`4029`（成本熔断，理论上 B台为 0 不触发）。
- **前端场景**：操作框「批量裂变」。提交后用 `batch_id` 轮询进度（见 5）。
- **异步**：**是**。**轮询**：**是**（轮询接口 5）。**花钱**：**否**（本地 ffmpeg，成本 0，可放心大批量）。**进候选池**：否。

## 5) `GET /api/b/batch/{batch_id}` —— 批量裂变进度
- **方法/Header**：GET + Bearer。
- **返回 `data`**：`{ "batch_id","status":"queued|running|done|failed","total_outputs","completed","failed","video_ids":[...] }`。
- **错误码**：`3001`（批次不存在/非本租户）。
- **前端场景**：提交批量裂变后轮询，`status=done` 时刷新裂变陈列面（`GET /api/videos?type=viral&batch_id=...`）。
- **异步**：—。**轮询**：**是**（建议 1~2s 间隔，done/failed 停止）。**花钱**：否。

## 6) `DELETE /api/videos/{id}` —— 删除视频（soft delete）
- **方法/Header**：DELETE + Bearer。
- **返回 `data`**：`{ "video_id","storage_status":"deleted" }`。
- **权限**：`user`/`invite_admin` 只能删**本租户**视频；`super_admin` 可删任意租户。**跨租户 → HTTP 403**。
- **错误码**：`3001`（视频不存在）；`HTTP 403`（跨租户）。
- **前端场景**：用户对不满意的视频点「删除」。删服务器文件，DB 记录保留（`storage_status=deleted`，默认列表不再显示，`include_expired=true` 可见）。母视频/裂变/上传源视频同规则。
- **异步**：否。**轮询**：否。**花钱**：否。

## 7) `GET /api/storage/status` —— 存储状态（分角色）
- **方法/Header**：GET + Bearer。
- **返回 `data`**（按角色不同）：
  - `user` / `invite_admin`（scope=tenant）：
    `{ "scope":"tenant","tenant_id","mother_count","viral_count","upload_count","estimated_used_mb" }`
  - `super_admin`（scope=global）：
    `{ "scope":"global","disk_total_gb","disk_used_gb","disk_used_percent","mother_count","viral_count","upload_count","tenant_summary":[{tenant_id,mother_count,viral_count,upload_count}] }`
- **前端场景**：普通用户看自己占用；老板（super_admin）看全局 ECS 磁盘 + 各租户概览。**前端按 `scope` 字段决定渲染哪种视图**（不要假设有 disk 字段）。
- **异步**：否。**轮询**：否。**花钱**：否。

## 8) `POST /api/events/track` —— 行为埋点（回流层）
- **方法/Header**：POST JSON + Bearer。
- **请求体**：`{ "action":"play|select|send_to_b|download|export|favorite|dislike|delete", "video_id":123, "context":{...}? }`。
- **返回 `data`**：`{ "signal_id","action" }`。
- **错误码**：`2001`（action 非法 / video 非本租户）。
- **前端场景**：播放、选中、发送到 B台、下载、导出、收藏、点踩、删除时埋点。
- **异步**：否。**轮询**：否。**花钱**：否。**进候选池**：否（仅信号）。
- **失败是否阻断**：**不阻断**。埋点失败要静默吞掉，**绝不能阻断播放/下载/导出主流程**（fire-and-forget）。

## 9) `POST /api/videos/{id}/feedback` —— 视频反馈 → 候选池
- **方法/Header**：POST JSON + Bearer。
- **请求体**：`{ "rating":"good|bad", "tags":["适合获客","钩子好"], "note":"适合发小红书" }`。
- **返回 `data`**：`{ "signal_id","candidate_id","status":"pending" }`。
- **错误码**：`2001`（rating 非法 / video 非本租户）。
- **前端场景**：用户对视频点赞/点踩并写心得。
- **异步**：否。**花钱**：否。**进候选池**：**是**，生成一条 `knowledge_candidates`，`status=pending`，**不直接进正式大库**（需 super_admin 审核）。
- **失败是否阻断**：可提示但不必阻断主流程。

## 10) `GET /api/admin/knowledge-candidates?status=` —— 候选池列表（仅 super_admin）
- **方法/Header**：GET + Bearer（**super_admin**）。
- **请求参数**：`status=pending|approved|rejected|archived`（可选）。
- **返回 `data`**：`{ "items":[ {id,tenant_id,phone,source_module,source_type,video_id,batch_id,title,content_summary,tags,raw_ref,risk_level,status,created_at,reviewed_at,reviewed_by,review_note} ], "total":N }`。
- **权限**：非 super_admin → **HTTP 403**。
- **前端场景**：老板的「知识候选池」审核台。**仅 `super_admin` 入口可见**（用 `/api/me` 判断）。
- **异步**：否。**花钱**：否。

## 11) `POST /api/admin/knowledge-candidates/{id}/approve` —— 审核通过（仅 super_admin）
- **方法/Header**：POST JSON + Bearer（**super_admin**）。
- **请求体**：`{ "note":"入库" }`（可选）。
- **返回 `data`**：候选完整对象，`status=approved`、`reviewed_by`、`reviewed_at` 已填。
- **错误码**：`3001`（候选不存在）；`HTTP 403`（非 super_admin）。
- **前端场景**：审核台「通过」。**P0 仅置 approved，不推送阿里云大库**（导出留 P1）。
- **异步**：否。**花钱**：否。

## 12) `POST /api/admin/knowledge-candidates/{id}/reject` —— 驳回（仅 super_admin）
- 同 11，`status=rejected`。请求体 `{ "note":"不合适" }`（可选）。

---

## 配套（已在前序补丁交付，前端常用）
| 接口 | 用途 |
|----|----|
| `POST /api/auth/login` `{phone, invite_code}` | 登录，返回 `{token, tenant_id, role}` |
| `GET /api/me` | `{phone,tenant_id,role,is_admin,permissions}`，控制管理员入口 |
| `POST /api/a/generate` `{prompt,title?,duration,resolution,image_file_id?}` | **A台生成母视频（异步，会花钱！）**，返回 `{task_id}`，轮询 `GET /api/tasks/{id}` |
| `POST /api/generate` `{text}` | 一句话批量（A台，会花钱），超 `max_a_batch`(10) → `2001` |
| `GET /api/tasks/{task_id}` | 任务状态 `{status,progress,result,error}`，A台轮询用 |
| `POST /api/export/videos` | 选中视频 → mp4 下载 URL 列表（前端逐条下载） |
| `GET /api/b/strategies` | B台可选内容策略 |
| `GET /api/subscription/status` | `{status,trial_remaining,quota_remaining}` |

---

## 前端必须遵守的红线（重点）
1. **A台会花钱**（火山）：`/api/a/generate`、`/api/generate` 前端必须给用户**明确费用提示/二次确认**；一句话批量超 10 条后端会拒（`2001`）。
2. **B台 0 成本**：`/api/b/batch-generate` 本地 ffmpeg，可放心批量，**不要**给用户「会花钱」的误导提示。
3. **埋点 fire-and-forget**：`/api/events/track` 失败**绝不阻断**播放/下载/导出。
4. **反馈只进候选池**：`/api/videos/{id}/feedback` 产出 `pending` 候选，**不是**直接入正式大库；前端文案不要写「已入库」。
5. **上传视频会进陈列面**：批量上传 video 成功后，刷新 `GET /api/videos?type=mother` 即可看到（`source_type=uploaded`），解决「上传了不知道去哪用」。
6. **裂变结果进裂变陈列面**：批量裂变 `done` 后刷新 `GET /api/videos?type=viral&batch_id=...`。
7. **storage/status 按 scope 渲染**：普通用户无 `disk_*` 字段，前端读 `scope` 区分，不要硬取全局磁盘。
8. **管理员入口靠 `/api/me`**：`role=super_admin` 显示「候选池审核 + 全局存储」，`invite_admin` 只显示「发码」，`user` 不显示管理员入口。

---

## 错误码速查
| code / HTTP | 含义 |
|----|----|
| `0` | 成功 |
| `2001` / HTTP 422 | 参数错误 / 业务校验失败（action 非法、源视频非本租户、批量超限、A台一句话超额…） |
| `1001` / HTTP 401 | 未登录 / 令牌无效或过期 |
| `1001` / HTTP 403 | 无权限（跨租户删除、非 super_admin 访问候选池/全局存储） |
| `1002` | 邀约码无效或已用尽（登录） |
| `4010` | 邀请码已绑定其他手机号（登录） |
| `3001` | 资源不存在（视频 / 批次 / 候选） |
| `4029` | 成本熔断（A台配额超限） |
