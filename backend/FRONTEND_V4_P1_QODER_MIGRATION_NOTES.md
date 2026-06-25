# 前端迁移要点（Qoder）· V4 P1 B台裂变

> 一页速查。配套 `FRONTEND_V4_REDESIGN_API_CONTRACT.md`（完整合同）+ L3 交互规格。
> 后端分支 `claude/v4-staging`（已就绪）。所有接口带 `Authorization: Bearer <JWT>`。

---

## 1. B台请求体：旧 `sources` → 新 `source_video_ids`（必改）

### ❌ 旧（P0，已不推荐）
```json
POST /api/b/batch-generate
{ "sources": [ {"source_video_id":11,"count":10}, {"source_video_id":12,"count":10} ],
  "prompt":"抗衰主题", "total_limit":50 }
```

### ✅ 新（P1 标准）
```json
POST /api/b/batch-generate
{ "prompt":"抗衰主题",
  "source_video_ids":[11,12,13],   // 前端维护的 current_source_video_ids（合格者）
  "auto_ratio":10,                  // 固定 10（1:10），可省略
  "max_outputs":50,                 // 固定 50，可省略
  "strategy":"mix" }                // 可省略
```
> 后端仍兼容旧 `sources`，但**前端请改用 `source_video_ids`**。`auto_ratio/max_outputs/strategy` 都有默认值，最简可只传 `{prompt, source_video_ids}`。

### 返回（新增字段，需处理）
```json
{ "code":0, "data":{
    "batch_id":"...",
    "source_count":5,                    // 实际参与的合格源数（≤5）
    "total_outputs":50,                  // 计划产出条数 = source_count*10，封顶 50
    "ignored_source_video_ids":[16],     // 超过 5 个时被忽略的源 → 可提示用户
    "status":"queued",
    "cost":0 } }
```
- 拿到 `batch_id` 后**轮询** `GET /api/b/batch/{batch_id}`（每 1.5s），`status=done` 停止。
- 若 `ignored_source_video_ids` 非空 → 提示「本次仅使用前 5 个源视频，其余未参与」。

---

## 2. `current_source_video_ids`：前端会话源池（新增逻辑）

前端在内存维护本次会话的源视频池：
1. **上传视频**成功后（`POST /api/uploads/batch` 返回 `uploaded[].video_id` 非空）→ 把这些 `video_id` 加入 `current_source_video_ids`。
2. **A台生成母视频**完成后（compose 任务 done）→ 把新母视频 id 也加入。
3. 用户在「高级选择」手动增删 → 直接改这个数组。
4. 点 B台时，提交 `source_video_ids = current_source_video_ids` 中的**合格**者（见 §3）。
5. 若前端没维护/为空 → 不传该字段，后端会 fallback 到最近合格历史源（兜底，不是主流程）。

---

## 3. B台按钮可用性：30 秒硬门槛（前端先判断）

合格源视频 = 列表项里 `duration_seconds != null && duration_seconds >= 30`。
- 合格数 `>= 3` → B台按钮**可点**。
- 合格数 `< 3` → 按钮**禁用** + tooltip「至少上传3个时长30秒以上的视频」；强行点弹门槛弹窗（文案见 L3 §3.2）：
  `请至少上传3个时长30秒以上的视频。当前：N个视频，最长XX秒`
- `duration_seconds === null`（时长未知）按**不合格**处理，列表卡片显示「时长未知（需重新上传或等待解析）」。

> 后端有兜底：合格<3 时返回 `code:2001`，message =「请至少上传 3 个时长 30 秒以上的视频，才能稳定裂变。」前端可直接用该 message。

---

## 4. 列表读 `duration_seconds`（新增字段）

`GET /api/videos?type=mother|viral` 的每个 item 新增 **`duration_seconds`**（秒，可能为 null）。
- 卡片显示时长用它；
- B台门槛判断用它；
- null → 显示「时长未知」。

---

## 5. A台主入口 = `POST /api/compose`（不是 /api/a/generate）

- 主工作台「🟠 A台·母视频」按钮 → `POST /api/compose {prompt, total_seconds, resolution, title?, image_file_ids?}`。
- `/api/a/generate` 是底层单段/技术备用，**不要**作为主按钮入口。
- 点击前弹费用确认（文案固定，不写单价）：
  `A台会调用火山API生成母视频，具体费用以实际扣费为准。确认继续吗？`
- 确认后异步，轮询 `GET /api/tasks/{task_id}`，done 后刷新母视频陈列面。
- 余额/试用不足 → 后端 `code:4029`，前端弹「额度不足/试用次数不足」类提示。

---

## 6. 不变 / 复用（避免重复造）
- 删文本上传入口、删蓝色「上传素材」按钮、取消勾选确认 → 纯前端，后端无对应改动。
- 批量下载：`POST /api/export/videos`（沿用）。
- 删除：`DELETE /api/videos/{id}`（user 仅本租户，跨租户 403）。
- 存储栏：`GET /api/storage/status` 按返回的 `scope`（tenant/global）渲染，普通用户无 `disk_*` 字段。
- 埋点 `POST /api/events/track`：fire-and-forget，**失败不阻断**播放/下载/导出。
- 反馈 `POST /api/videos/{id}/feedback`：进候选池 pending，**非入正式大库**；文案别写「已入库」。
- 候选池入口仅 `super_admin`（用 `GET /api/me` 的 `role` 判断）。

---

## 7. 改动清单（给 Qoder 排期）
| 改动 | 优先级 |
|----|----|
| B台请求体 `sources` → `source_video_ids` + 处理新返回字段（ignored/source_count） | 必改 |
| 维护 `current_source_video_ids`（上传/生成后加入） | 必改 |
| B台按钮门槛改读 `duration_seconds≥30`，合格<3 禁用 | 必改 |
| 列表卡片读 `duration_seconds`（null→时长未知） | 必改 |
| A台主按钮指向 `/api/compose` + 费用确认文案（不写单价） | 必改 |
| 删文本入口/蓝按钮/取消勾选 | 必改（纯前端） |
| ignored_source_video_ids 提示「仅用前5个」 | 建议 |
