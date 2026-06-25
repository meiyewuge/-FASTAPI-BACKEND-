# V4 前端接口合同（当前唯一真源）· FRONTEND_V4_CURRENT_API_CONTRACT

> **本文件是 Qoder 前端开发的唯一接口依据。** 取代旧版 `FRONTEND_V4_REDESIGN_API_CONTRACT.md`。
> 与 `FRONTEND_V4_P1_QODER_MIGRATION_NOTES.md`（B台迁移）、`FRONTEND_V4_P0B_PREVIEW_QODER_NOTES.md`（A台 preview）一致，三份冲突时**以本文件为准**。
> 后端分支 `claude/v4-staging`。统一返回壳 `{code,message,data}`，`code==0` 成功。
> **除登录外所有接口都要带 `Authorization: Bearer <JWT>`**。tenant_id / phone 一律由后端从 JWT 解析，前端不传、传了也不信任。

---

## 1. 登录与权限

### `POST /api/auth/login`（无需 JWT）
- 请求：`{ "phone":"...", "invite_code":"..." }`
- 返回 `data`：`{ "token":"<JWT>", "tenant_id":"...", "role":"super_admin|invite_admin|user" }`
- 错误：`1002` 邀约码无效/已用尽；`4010` 邀请码已绑定其他手机号。

### `GET /api/me`（JWT）
- 返回 `data`：`{ "phone","tenant_id","role","is_admin":bool,"permissions":[...] }`
- 前端据此渲染入口：`role=super_admin` 显示管理员后台 + 候选池；`invite_admin` 只显示发码；`user` 不显示管理员入口。

**权限规则（Patch6 保持不变）**
- `super_admin`：全部（发码 + 授权员工 + 候选池审核 + 全局存储）。
- `invite_admin`：发码/看码/作废码；**不能**授权他人、不显示候选池。
- `user`：仅使用系统。
- **ADMIN_KEY 不恢复为前端发码通道**：前端日常一律用 JWT；ADMIN_KEY 仅后端 bootstrap/应急，前端不持有、不发送。

---

## 2. 上传素材

### `POST /api/uploads/batch`（JWT，`multipart/form-data`）
- 字段：`files`（可重复，混合 image/video/file）、`texts`（可重复，文本内容）。
- 约束：image jpg/png/webp ≤10MB；video mp4/mov/avi ≤500MB；file doc/docx/zip ≤50MB；每类 ≤10 个；单批总量 ≤2GB。
- 返回 `data`：
```json
{ "uploaded":[ {"file_id","file_name","file_type","file_size","file_url","thumbnail_url","status","video_id","zip_entries?"} ],
  "failed":[ {"file_name","reason"} ] }
```
- **上传视频** → `video_id` 非空，自动进入母视频/源视频陈列面（`type=mother&source_type=uploaded`），并加入前端会话 `current_source_video_ids`。
- **上传图片** → 用 `file_id`（即 image_file_id）传给 A台 preview 的 `image_file_ids`。
- **图片顺序决定 role**：第 1 张 = first_frame，第 2-9 张 = reference_image（见 §3）。前端可拖拽排序。
- 异步否；不花钱。单文件失败进 `failed[]`，不阻断其余。

---

## 3. A 台 Director-Prompt 预览（不花钱，不调火山）

### `POST /api/compose/preview`（JWT）
- 请求：
```json
{ "prompt":"达芙荻丽奢华油，夏季干皮上妆卡粉救星，99%天然植萃",
  "image_file_ids":["fid1","fid2","fid3"],   // 可空=纯文生
  "style":"premium",                          // premium | fresh | chinese
  "ratio":"9:16", "duration":15, "resolution":"1080p" }
```
- 返回 `data`：
```json
{ "director_plan_id":"...",                    // 正式生成必用
  "director_plan":{ "brand_context":{...}, "storyboard":[{index,timecode,description,line,image_ref}], "versions":{...} },
  "seedance_text_prompt":"【T1-...】...【T5-...】",
  "seedance_content":[ {"type":"text",...}, {"type":"image_url","image_url":{"url"},"role":"first_frame"}, ... ],
  "image_roles":[ {"file_id","role":"first_frame|reference_image","url":"https://..."} ],
  "estimated_cost":37.20,
  "ratio":"9:16","resolution":"1080p","duration":15,
  "generate_audio":true,
  "warnings":[ "..." ] }
```
- **preview 不调用火山、不扣费**；结果落 director_plans 供正式 compose 复用。
- 图片不可访问 → `code:2002`（见 §12）。
- 异步否。前端展示：分镜卡片、可折叠 T1-T5 提示词、图片角色角标（首帧/参考图）、`estimated_cost` 费用、`warnings`。

---

## 4. A 台正式 compose（受控，默认锁）

### `POST /api/compose`（JWT）
- 请求（**必须先 preview 拿 director_plan_id**）：
```json
{ "director_plan_id":"...", "confirmed_cost":true, "total_seconds":15 }
```
- 返回：`code:0` → `data:{ "task_id","director_plan_id" }`，轮询 `GET /api/tasks/{task_id}`。
- **前端不能绕过 preview 直接 compose**：无 `director_plan_id` 且无 `prompt` → `2001`；未 `confirmed_cost` → `2001`。
- **ENABLE_COMPOSE=false（当前默认）** → `code:4031`「生成通道维护中，暂不可用。」前端 A台生成按钮置灰 + 显示该文案。
- 余额/试用/额度不足 → `code:4029`（单独提示，见 §12）。
- 异步是；**会花钱**（火山）；进候选池否。

---

## 5. B 台 P1 裂变（0 成本）

### `POST /api/b/batch-generate`（JWT）
- **P1 标准请求体**（前端主字段）：
```json
{ "prompt":"抗衰主题", "source_video_ids":[1,2,3], "auto_ratio":10, "max_outputs":50, "strategy":"mix" }
```
- `source_video_ids`：前端会话 `current_source_video_ids` 中的合格者（`duration_seconds>=30`）。
- `sources`：**仅兼容旧版 P0，不能作为前端主字段**。
- 选源三层优先级：传入 `source_video_ids` 优先 → 用户手选 → 为空时后端 fallback 最近合格源。
- 合格门槛（硬）：`type=mother` + `storage_status=active` + `duration_seconds>=30`；合格<3 → `2001`「请至少上传 3 个时长 30 秒以上的视频，才能稳定裂变。」
- 1:10：3→30、4→40、5→50；超 5 个只取前 5，封顶 50。
- 返回 `data`：
```json
{ "batch_id":"...", "source_count":5, "total_outputs":50, "ignored_source_video_ids":[16], "status":"queued", "cost":0 }
```
- 异步是（轮询 §6）；**不花钱**（本地 ffmpeg，cost=0）。`ignored_source_video_ids` 非空 → 提示「本次仅使用前 5 个源视频」。

---

## 6. B 台轮询

### `GET /api/b/batch/{batch_id}`（JWT）
- 返回 `data`：`{ "batch_id","status":"queued|running|done|failed","total_outputs","completed","failed","video_ids":[...] }`
- 建议每 1.5s 轮询，`done/failed` 停止。
- `done` 后刷新裂变陈列面：`GET /api/videos?type=viral&batch_id=xxx`。
- 错误：`3001` 批次不存在/非本租户。

---

## 7. 视频列表 / 陈列面

### `GET /api/videos`（JWT）
- 参数：`type=mother|viral|all`、`source_type=generated|uploaded|remixed`、`batch_id`、`store_id`、`source_video_id`、`strategy`、`page`、`page_size`、`sort=created_desc|created_asc`、`include_expired=false`。
- 母视频/源视频陈列面：`GET /api/videos?type=mother`（含 A台 generated + 上传 uploaded）。
- 裂变视频陈列面：`GET /api/videos?type=viral`。
- 每个 item 必含：
```json
{ "video_id","type","source_type","storage_status","expires_at","duration_seconds",
  "title","strategy","store_id","source_video_id","parent_video_id","batch_id",
  "download_url","share_url","cover_url","thumbnail_url" }
```
- `duration_seconds` 可能为 `null`（时长未知）→ 卡片显示「时长未知」，B台门槛按不合格处理。

### `DELETE /api/videos/{id}`（JWT）
- user/invite_admin 仅删本租户；super_admin 删任意租户；跨租户 → **HTTP 403**。soft delete（删文件 + `storage_status=deleted`，DB 记录保留）。错误 `3001` 不存在。

---

## 8. 存储状态（分角色）

### `GET /api/storage/status`（JWT）
- `user` / `invite_admin` → `scope=tenant`：`{scope:"tenant",tenant_id,mother_count,viral_count,upload_count,estimated_used_mb}`，**无全局磁盘字段**。
- `super_admin` → `scope=global`：`{scope:"global",disk_total_gb,disk_used_gb,disk_used_percent,mother_count,viral_count,upload_count,tenant_summary:[...]}`。
- 前端按返回的 `scope` 渲染，**不要硬取 disk_* 字段**。

---

## 9. 行为埋点

### `POST /api/events/track`（JWT）
- 请求：`{ "action":"play|select|send_to_b|download|export|favorite|dislike|delete", "video_id?":123, "context?":{...} }`
- **fire-and-forget**：失败**静默忽略，绝不阻断**播放/下载/删除/导出。tenant/phone 取自 JWT。
- 错误 `2001`（action 非法 / video 非本租户）——前端忽略即可。

---

## 10. 反馈 → 候选池

### `POST /api/videos/{id}/feedback`（JWT）
- 请求：`{ "rating":"good|bad", "tags":["..."], "note":"..." }`
- 返回 `data`：`{ "signal_id","candidate_id","status":"pending" }`
- **只进候选池 pending，不直接进正式大库**。前端文案：**「已加入候选池，待审核」**（不要写「已入库」）。
- 失败 `2001` → 可提示「反馈提交失败，请重试」，不影响播放/下载。

---

## 11. 候选池（仅 super_admin）

### `GET /api/admin/knowledge-candidates?status=`（super_admin）
- 返回 `data`：`{ "items":[ {id,tenant_id,phone,source_module,source_type,video_id,batch_id,title,content_summary,tags,raw_ref,risk_level,status,created_at,reviewed_at,reviewed_by,review_note} ], "total" }`

### `POST /api/admin/knowledge-candidates/{id}/approve`（super_admin） · `{ "note?":"..." }` → status=approved
### `POST /api/admin/knowledge-candidates/{id}/reject`（super_admin） · `{ "note?":"..." }` → status=rejected
- **入口仅 super_admin 渲染**；user/invite_admin 不显示候选池区域（后端也 403 双保护）。
- P0/P1 审核通过仅置状态，**不推送阿里云大库**（导出留后续）。

---

## 12. 错误码表（统一）

| code / HTTP | 含义 | 前端处理 |
|----|----|----|
| `0` | 成功 | — |
| `1001` / HTTP 401 | 未登录 / 令牌无效或过期 | 跳登录页 |
| `1001` / HTTP 403 | 权限不足（跨租户删除、非 super_admin 访问候选池/全局存储） | 提示「该功能需要管理员权限」/「无权操作」 |
| `1002` | 邀约码无效或已用尽（登录） | 登录页提示 |
| `4010` | 邀请码已绑定其他手机号（登录） | 登录页提示 |
| `2001` / HTTP 422 | 参数/业务校验失败：未确认费用、缺 director_plan、**B台合格源视频<3（duration_seconds<30 或 NULL 不合格）**、A台一句话超额、action 非法 | 按场景提示；B台不足弹门槛弹窗「请至少上传3个时长30秒以上的视频」 |
| **`2002`** | **图片无法被视频模型访问** | 弹「图片无法被视频模型访问，请重新上传或等待处理完成。」 |
| **`4031`** | **A台 compose 熔断锁（生成通道维护中）** | A台生成按钮置灰 + 显示「生成通道维护中，暂不可用。」 |
| `4029` | 额度/余额/试用不足（成本熔断） | 弹「额度不足，请联系管理员充值」 |
| `3001` | 资源不存在（视频 / 批次 / 候选 / director_plan 过期） | 提示重试 / 重新 preview |

---

## 13. 关键红线（前端必须遵守）
1. **A台必须先 preview 后 compose**：不得直接调 `/api/compose` 生成；compose 必带 `director_plan_id + confirmed_cost`。
2. **A台会花钱**（火山）：费用确认用 preview 的 `estimated_cost`，不写固定单价；锁态（4031）置灰。
3. **B台 0 成本**：用 `source_video_ids`，不要给「会花钱」误导；裂变可放心批量。
4. **埋点 fire-and-forget**：`/api/events/track` 失败绝不阻断主流程。
5. **反馈只进候选池**：文案「已加入候选池，待审核」，非「已入库」。
6. **上传视频进母视频陈列面；裂变结果进裂变陈列面**。
7. **storage/status 按 scope 渲染**；管理员入口靠 `/api/me`。
8. **不恢复 ADMIN_KEY 前端发码**：一律 JWT。

---

## 14. 典型流程串联
```
登录 → /api/me 定角色
上传素材 → /api/uploads/batch（图片得 file_id；视频进母视频面 + current_source_video_ids）
A台：/api/compose/preview（导演稿+估价，不花钱）→ 用户确认 → /api/compose{director_plan_id,confirmed_cost}
       （ENABLE_COMPOSE=false → 4031 置灰）
B台：/api/b/batch-generate{source_video_ids,...} → 轮询 /api/b/batch/{id} → done → /api/videos?type=viral&batch_id
列表：/api/videos?type=mother|viral（读 duration_seconds/cover_url/...）
删除：DELETE /api/videos/{id}（本租户；super_admin 全局）
埋点/反馈：/api/events/track（不阻断）/ /api/videos/{id}/feedback（候选池 pending）
候选池审核：仅 super_admin
```
