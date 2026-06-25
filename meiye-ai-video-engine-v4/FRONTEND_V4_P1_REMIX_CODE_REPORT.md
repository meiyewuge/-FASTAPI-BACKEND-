# FRONTEND_V4_P1_REMIX_CODE_REPORT

> Qoder 前端 V4 P1 · B台裂变真实工作流 代码报告
> 分支: `qoder/v4-frontend-workbench`
> 后端基线: `claude/v4-staging` @ `143e6eb`（P1 B台裂变真实工作流）

---

## 1. commit 号

- **`5c0d408`**（`feat(frontend): V4 P1 B台裂变真实工作流`）
- 分支: `qoder/v4-frontend-workbench`

## 2. 修改文件

| 文件 | 变更 |
|------|------|
| `frontend/api/client.ts` | VideoItem 新增 `duration_seconds`/`source_type`/`storage_status`/`parent_video_id`/`batch_id`/`thumbnail_url`；`listVideos` 支持 `batchId` 参数；`BatchUploadItem` → `BatchUploadedItem` + `BatchUploadFailedItem`（P1 标准 uploaded/failed 响应）；`batchGenerate` 改 P1 标准体（source_video_ids/auto_ratio/max_outputs/strategy）；`BatchGenerateResult` 新增 `ignored_source_video_ids`/`cost`；`BatchStatus` 新增 `queued`/`video_ids`；`pollBatchStatus` 默认间隔 1.5s；`videoFeedback` 改 P1 标准（rating:good\|bad + tags + note）；`trackEvent` 改 `action` 字段 |
| `frontend/pages/Workbench.tsx` | 完全重写 P1：删除文本入口/蓝色上传素材按钮/勾选确认流程；新增 `current_source_video_ids` 会话源池；上传视频自动加入源池；A台主入口 `compose()` + 费用确认 + 轮询 + 产出加入源池；B台自动选源 + duration_seconds ≥ 30 硬门槛 + 3→30/4→40/5→50 预计产出；裂变完成自动刷新 + 自动滚动；反馈文案"加入候选池，待审核" |
| `frontend/styles.css` | 删除 batch-config-panel/row/estimate/submit 旧样式；新增 `@keyframes load` 进度动画；保留 batch-progress 进度条样式 |
| `frontend/pages/AdminPanel.tsx` | 未修改（P0 候选池 Tab 保持 super_admin only） |
| `frontend/main.tsx` | 不变 |
| `frontend/pages/Login.tsx` | 不变 |

## 3. 是否删除文本入口 — ✅ 是

- Workbench.tsx 中 `📝 文本` 按钮已移除
- `textExtra` 状态已移除
- 上传区仅保留：🖼️ 图片 / 📁 文件 / 🎬 视频

## 4. 是否删除蓝色上传素材按钮 — ✅ 是

- `btn btn-primary` 蓝色"上传素材"按钮已移除
- `action-bar` 仅保留：A台·母视频 + B台·裂变
- 上传改为选中文件后自动上传（无需手动点按钮）

## 5. 是否维护 current_source_video_ids — ✅ 是

- `useState<number[]>([])` 内存维护
- 上传视频成功 → 返回的 `video_id` 加入（`uploaded[].video_id` 非空）
- A台 compose done → 新母视频 id 加入
- B台提交时优先提交 `qualifiedSources.slice(0, 5)`
- 删除视频时从源池移除

## 6. 是否使用 source_video_ids — ✅ 是

- `batchGenerate()` 请求体: `{ source_video_ids: [...], prompt, auto_ratio: 10, max_outputs: 50, strategy: "mix" }`
- 不再使用 `sources` 作为主字段
- 不再使用旧字段 `count`

## 7. 是否读取 duration_seconds — ✅ 是

- `VideoItem` 类型新增 `duration_seconds?: number | null`
- 卡片显示：`duration_seconds` 有值 → `M:SS` 格式；`null` → 橙色"时长未知"
- B台门槛判断使用 `duration_seconds >= 30`

## 8. 是否实现 3 个 30 秒硬门槛 — ✅ 是

- `qualifiedSources = currentSourceVideoIds.filter(id => video.duration_seconds != null && duration_seconds >= 30)`
- `qualifiedCount < 3` → B台按钮 disabled
- 点击时弹出门槛提示："暂无法裂变。请至少上传3个时长30秒以上的视频。当前：N个视频，最长XX秒"
- `duration_seconds === null`（时长未知）按不合格处理

## 9. 是否实现 3→30 / 4→40 / 5→50 预计产出 — ✅ 是

- `estimatedOutputs = qualifiedCount >= 5 ? 50 : qualifiedCount * 10`
- B台按钮副标显示："合格源 N 个 → 预计 X 条"
- 超过 5 个：显示"本轮最多使用前5个合格视频，预计生成50条"
- `ignored_source_video_ids` 非空时显示提示

## 10. 是否接入 /api/compose — ✅ 是

- A台主按钮调用 `compose(prompt, 60, "1080p")` → `POST /api/compose`
- 返回 `task_id` → 轮询 `pollTask(taskId, onTick)` → done 刷新母视频陈列面
- **不接入** `/api/a/generate`（仅底层备用）

## 11. 是否取消"联系管理员操作" — ✅ 是

- A台费用确认文案："A台会调用火山API生成母视频，具体费用以实际扣费为准。确认继续吗？"
- 确认按钮："确认生成" / 取消按钮："取消"
- 余额不足显示："余额不足，请联系管理员充值"（code 4029）
- **不再显示** "请联系管理员操作"

## 12. 是否轮询 batch — ✅ 是

- `pollBatchStatus(batchId, onTick)` 默认 1.5s 间隔
- 显示进度："正在裂变… N / M"
- `done` 停止轮询，`failed` 也停止

## 13. 是否自动刷新裂变视频陈列面 — ✅ 是

- `done` 后调用 `loadViral(1, batchId)` → `GET /api/videos?type=viral&batch_id=xxx`
- 自动滚动到裂变视频区域：`viralRef.current.scrollIntoView({ behavior: "smooth" })`
- 不需要用户手动刷新

## 14. 是否保持 Patch6 权限 — ✅ 是

| 项目 | 状态 |
|------|------|
| `/api/me` 登录后获取角色 | ✅ 不变 |
| `isAdmin()` / `isSuperAdmin()` | ✅ 不变 |
| `ENABLE_ADMIN_KEY_FALLBACK` | ✅ `false` |
| 管理员接口鉴权 | ✅ 纯 Bearer JWT |
| ADMIN_KEY | ✅ 不恢复 |
| 候选池仅 super_admin 可见 | ✅ `isSuper` 判断 |
| A台不是管理员专属 | ✅ 普通用户也可点击（费用确认后） |

## 15. build 是否通过 — ✅ 是

```
vite v5.4.21 building for production...
✓ 37 modules transformed.
dist/index.html                   0.41 kB │ gzip:  0.32 kB
dist/assets/index-oOzWbSH-.css   16.11 kB │ gzip:  3.66 kB
dist/assets/index-C1QHdYIS.js   236.69 kB │ gzip: 77.02 kB
✓ built in 674ms
```

## 16. 是否可以交 ChatGPT 审核 — ✅ 可以

前端 P1 全部按文档实现，可提交 ChatGPT 审核。

---

## 20 项自查清单

| # | 检查项 | 状态 |
|---|--------|------|
| 1 | build 通过 | ✅ |
| 2 | 文本入口已删除 | ✅ 📝文本按钮已移除 |
| 3 | 蓝色上传素材按钮已删除 | ✅ btn-primary 已移除 |
| 4 | 图片/文件/视频入口保留 | ✅ 三个 upload-btn |
| 5 | 上传视频后进入母视频陈列面 | ✅ loadMother(1) 刷新 |
| 6 | 上传视频后加入 current_source_video_ids | ✅ uploaded[].video_id → setState |
| 7 | duration_seconds 正确显示 | ✅ fmtDuration / "时长未知" |
| 8 | 1/2 个合格视频时 B 台禁用 | ✅ qualifiedCount < 3 → disabled |
| 9 | 3 个合格视频时 B 台可用，预计 30 条 | ✅ 3*10=30 |
| 10 | 5 个合格视频时预计 50 条 | ✅ min(5*10, 50)=50 |
| 11 | B 台请求体使用 source_video_ids | ✅ batchGenerate(sourceIds, prompt) |
| 12 | 不再用 sources 作为主字段 | ✅ 请求体无 sources |
| 13 | B 台轮询 batch 状态 | ✅ pollBatchStatus 1.5s |
| 14 | done 后自动刷新裂变陈列面 | ✅ loadViral + scrollIntoView |
| 15 | A 台主按钮调用 /api/compose | ✅ compose(prompt, 60, "1080p") |
| 16 | A 台费用确认文案正确 | ✅ "以实际扣费为准" |
| 17 | A 台不再显示"联系管理员操作" | ✅ 已移除 |
| 18 | Patch6 权限未破坏 | ✅ ENABLE_ADMIN_KEY_FALLBACK=false |
| 19 | 候选池仅 super_admin 可见 | ✅ isSuper 判断 |
| 20 | events/track 失败不阻断主流程 | ✅ try/catch + console.warn |

---

## 约束遵守

| 约束 | 状态 |
|------|------|
| 不改后端 | ✅ |
| 不碰 production | ✅ |
| 不触发真实 A 台火山生成 | ✅ compose 仅前端逻辑，联调时由后端控制 |
| 不做大文件压测 | ✅ |
| 不做真实 50 条压测 | ✅ |
| 不恢复 ADMIN_KEY 模式 | ✅ |

## 联调注意

1. 后端 P1 部署到 staging 后方可联调
2. 需执行 `ALTER TABLE videos ADD COLUMN duration_seconds FLOAT;` + `python -m tasks.backfill_duration`
3. 上传响应格式需对齐 P1 标准（`uploaded[]` + `failed[]`）
4. compose 返回 `task_id` 格式需与 `/api/tasks/{id}` 对齐
