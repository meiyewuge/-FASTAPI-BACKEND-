# Qoder V4 P1.1 前端 Staging Smoke Test 验收报告

> **验收时间**：2026-06-24  
> **验收人**：Qoder（前端代码级审查）  
> **验收方式**：代码静态审查 + 接口合同对照（无真实 staging 环境联调）  
> **后端修复目标**：B台裂变视频 PTS 卡死 + MD5 重复（扣子部署）  
> **前端代码版本**：commit `b0e0741`（qoder/v4-frontend-workbench 分支）

---

## 1. 测试环境

| 项目 | 值 |
|------|-----|
| 前端框架 | React 18 + TypeScript 5 + Vite 5 |
| 构建结果 | vite build 666ms，0 error / 0 warning |
| API 绑定层 | `frontend/api/client.ts`（806 行） |
| 核心页面 | `frontend/pages/Workbench.tsx`（935 行） |
| 接口合同 | `FRONTEND_V4_CURRENT_API_CONTRACT.md`（219 行，14 节） |
| 鉴权方式 | JWT Bearer（Patch6，ENABLE_ADMIN_KEY_FALLBACK=false） |
| staging 后端 | 扣子部署中，前端未接真实 staging |

> **说明**：本次验收为代码级静态审查，基于前端代码与接口合同的兼容性分析。真实 staging 联调需等扣子部署完成后进行。

---

## 2. 测试账号

| 角色 | 说明 |
|------|------|
| super_admin | 可见管理后台 + 候选池 Tab |
| invite_admin | 可见管理后台，不可见候选池 |
| user | 无管理入口 |

> 账号由 `POST /auth/login`（phone + invite_code）获取 JWT，前端通过 `GET /api/me` 获取角色。P1.1 不涉及鉴权变更。

---

## 3. 测试入口

| 入口 | 代码位置 | 说明 |
|------|----------|------|
| A台预览 | `Workbench.tsx:327 handlePreview()` | POST /compose/preview |
| A台生成 | `Workbench.tsx:347 handleComposeConfirm()` | POST /compose（需 preview 前置） |
| B台裂变 | `Workbench.tsx:408 handleBClick()` | POST /b/batch-generate |
| 母视频列表 | `Workbench.tsx:217 loadMother()` | GET /videos?type=mother |
| 裂变视频列表 | `Workbench.tsx:222 loadViral()` | GET /videos?type=viral |
| 批量上传 | `Workbench.tsx:250 doUpload()` | POST /uploads/batch |

---

## 4. 12 项验收点逐条审查

### 4.1 B台批量裂变入口是否正常

**代码路径**：`Workbench.tsx:680-688` → `handleBClick()`

| 检查项 | 结果 |
|--------|------|
| 按钮渲染 | `btn btn-b`，显示合格源数量 + 预计产出条数 |
| 禁用条件 | `!bEnabled \|\| !online`（qualifiedCount < 3 / batchRunning / composeRunning / 离线） |
| 门槛计算 | `qualifiedSources` = duration_seconds >= 30 的源视频，需 ≥ 3 个 |
| 请求参数 | `batchGenerate(sourceIds, prompt, strategy="mix", autoRatio=10, maxOutputs=50)` |
| 最多源数 | `sourceIds = qualifiedSources.slice(0, 5)` — 最多 5 个 |

**结论**：✅ 入口逻辑完整，门槛 + 参数与合同一致。

---

### 4.2 母视频选择 / 上传入口是否正常

**代码路径**：`Workbench.tsx:558-562`（视频上传）+ `Workbench.tsx:262-265`（video_id 入池）

| 检查项 | 结果 |
|--------|------|
| 上传入口 | `<input type="file" accept=".mp4,.mov,.avi" multiple>` |
| 批量上传 | `batchUpload(files, "video")` → POST /uploads/batch |
| 自动入池 | 上传成功后 `u.video_id` 自动加入 `currentSourceVideoIds` |
| A台产出 | `handleComposeConfirm` 成功后 `newIds` 也加入源池 |

**结论**：✅ 双入口（上传 + A台产出）均正确入池。

---

### 4.3 batch-generate 请求是否正常发起

**代码路径**：`client.ts:709-718` `batchGenerate()`

```
POST /b/batch-generate
{
  source_video_ids: number[],   // ✅ 不是 sources
  prompt?: string,
  auto_ratio: 10,
  max_outputs: 50,
  strategy: "mix"
}
```

| 检查项 | 结果 |
|--------|------|
| 端点路径 | `/b/batch-generate` ✅ |
| 参数字段 | `source_video_ids`（非旧版 `sources`）✅ |
| auto_ratio | 默认 10 ✅ |
| max_outputs | 默认 50 ✅ |
| 响应类型 | `BatchGenerateResult { batch_id, status, source_count, total_outputs, ignored_source_video_ids, cost }` ✅ |

**结论**：✅ 请求格式与合同完全一致。

---

### 4.4 batch 状态是否正常显示

**代码路径**：`Workbench.tsx:792-810`（进度条渲染）

| 检查项 | 结果 |
|--------|------|
| 进度显示 | `batchStatus.completed / batchStatus.total_outputs` + 百分比进度条 |
| 轮询间隔 | 1.5s（`pollBatchStatus` 默认） |
| 实时刷新 | `onTick` → `setBatchStatus(d)` 每次轮询更新 UI |
| 完成提示 | done → `裂变完成！X 条` / 有失败 → `部分失败，成功 X 条` |

**结论**：✅ 状态显示逻辑完整。

---

### 4.5 30 条 viral 视频是否能正常展示

**代码路径**：`Workbench.tsx:222-225` `loadViral()` + `Workbench.tsx:881-921` 渲染

| 检查项 | 结果 |
|--------|------|
| PAGE_SIZE | 50（行 147） |
| 30 条展示 | 30 < 50，单页全部展示，无需翻页 ✅ |
| 列表渲染 | `viralVideos.map(v => ...)` 以 `key={v.video_id}` 唯一键 |
| 卡片内容 | cover_url → video → placeholder + 标题 + 源ID + 时长 + 大小 + 剩余天数 |

**结论**：✅ 30 条在 PAGE_SIZE=50 下单页展示，无分页问题。

---

### 4.6 视频是否能从前端播放到结尾

**代码路径**：`Workbench.tsx:449-452` `handlePlay()`

```typescript
const handlePlay = (v: VideoItem) => {
  trackEvent("play", { video_id: v.video_id });
  window.open(v.download_url || v.share_url, "_blank");
};
```

| 检查项 | 结果 |
|--------|------|
| 播放方式 | `window.open(url, "_blank")` — 新标签页打开浏览器原生播放器 |
| 前端控制 | 无内嵌 `<video>` 播放控件，前端不控制播放过程 |
| PTS 卡死 | 14 秒卡死是后端视频编码 PTS 问题，**前端无法控制** |

**结论**：⚠️ 前端使用新标签页播放，播放体验完全依赖后端视频文件质量。P1.1 修复 PTS 后应能正常播放到结尾。**需在 staging 部署后真实验证**。

---

### 4.7 是否存在 14 秒后卡死现象

**分析**：

| 层级 | 前端能力 |
|------|----------|
| 前端 | `window.open(url)` 打开后完全由浏览器控制，前端无干预能力 |
| 后端 | PTS（Presentation Timestamp）是视频编码层问题，前端无法修复 |
| 修复范围 | P1.1 后端修复目标，前端无需改动 |

**结论**：✅ 前端不涉及此问题。等待后端 PTS 修复后 staging 验证。

---

### 4.8 视频列表是否有空白卡片、重复覆盖、分页异常

**代码审查**：

| 检查项 | 代码位置 | 结果 |
|--------|----------|------|
| 唯一键 | `key={v.video_id}`（行 883） | ✅ 不会重复渲染 |
| 空白卡片 | 三级 fallback：cover_url → video muted → "暂无预览" | ✅ 无空白 |
| 重复覆盖 | `listVideos("viral", page, PAGE_SIZE, batchId)` 每次覆盖式更新 | ✅ 无追加重复 |
| 分页逻辑 | `viralTotal > PAGE_SIZE` 才显示分页按钮（行 924） | ✅ 30 条不触发分页 |
| 边界处理 | `v.duration_seconds == null` → 显示 "时长未知"（行 895） | ✅ 不崩溃 |

**结论**：✅ 无空白卡片 / 重复覆盖 / 分页异常。

---

### 4.9 如果后端出现 partial_done，前端是否不崩溃

**⚠️ 关键发现 — 这是本次验收最重要的问题。**

**代码路径**：`client.ts:725-737` `pollBatchStatus()`

```typescript
// 行 734 — 终止条件
if (d?.status === "done" || d?.status === "failed" || r.code !== 0) return r;
```

| 检查项 | 结果 |
|--------|------|
| 终止状态 | 仅 `"done"` 和 `"failed"` |
| BatchStatus 类型 | `"queued" \| "running" \| "done" \| "failed"`（行 700） |
| partial_done | **未包含在终止条件和类型定义中** |

**风险分析**：

1. **无限轮询**：如果后端返回 `status: "partial_done"`，`pollBatchStatus()` 不会停止，将以 1.5s 间隔无限请求。
2. **TypeScript 类型不匹配**：`BatchStatus.status` 的 union type 不包含 `"partial_done"`，运行时虽然不会报 TS 编译错误（后端返回的 JSON 不受 TS 约束），但逻辑上走不到终止分支。
3. **UI 表现**：轮询不停 → `batchRunning` 永远为 `true` → B台按钮持续禁用 → 进度条卡在最后一个 tick 的值。

**Workbench.tsx 行 430-441 的完成处理**：

```typescript
pollBatchStatus(batch_id, (d) => setBatchStatus(d)).then((final) => {
  setBatchRunning(false);
  if (final.data?.status === "done") {
    // 刷新陈列面 + 滚动
  } else {
    showToast(`裂变结束: ${final.data?.status || "未知"}`);
    // ⚠️ partial_done 走到这里 — 会显示 toast 但不刷新视频列表
  }
});
```

**结论**：❌ **存在两个前端问题需小修**（详见第 6 节）。

---

### 4.10 A台 preview 是否不受影响

**代码路径**：`client.ts:241-256` `composePreview()` → `POST /compose/preview`

| 检查项 | 结果 |
|--------|------|
| 端点 | `/compose/preview` — 与 B台 remixer 完全独立 |
| P1.1 影响范围 | 后端仅修改 B台裂变视频 PTS + MD5，不涉及 /compose/preview |
| 前端代码 | `handlePreview()` 不依赖任何 B台状态 |

**结论**：✅ A台 preview 完全不受 P1.1 影响。

---

### 4.11 A台 compose 是否仍然显示锁定 / 4031

**代码路径**：`Workbench.tsx:382-386`

```typescript
} else if (r.code === 4031) {
  setComposeMaintenance(true);
  showToast("生成通道维护中，暂不可用。");
}
```

| 检查项 | 结果 |
|--------|------|
| 4031 处理 | `setComposeMaintenance(true)` → 按钮 `disabled` + 灰色样式 `btn-maintenance` |
| 按钮文案 | "🔧 生成通道维护中" |
| P1.1 影响 | compose 端点不受 P1.1 后端改动影响 |

**结论**：✅ 4031 锁定逻辑保持不变，P1.1 不影响 A台 compose。

---

### 4.12 前端是否需要小修

**结论：需要小修，共涉及 1 个文件 2 处改动。**

---

## 5. 30 条视频展示结果（代码级预测）

| 场景 | 预期表现 |
|------|----------|
| 30 条 viral 返回 | `viralVideos.length = 30`，PAGE_SIZE=50 单页展示 |
| 卡片渲染 | 每张卡：cover/video/placeholder + 标题 + 源ID + 时长 + 大小 + 剩余天数 |
| 操作按钮 | 播放 / 下载 / 删除 / 反馈（good/bad → 候选池） |
| 分页 | 30 < 50，不显示分页控件 |
| 排序 | 取决于后端返回顺序，前端未做额外排序 |

---

## 6. 播放结果（代码级预测）

| 场景 | 预期表现 |
|------|----------|
| 点击播放 | `window.open(download_url \|\| share_url, "_blank")` 新标签页打开 |
| PTS 修复前 | 视频在 ~14 秒处画面冻结（后端编码问题） |
| PTS 修复后 | 视频应能正常播放到结尾 |
| 下载 | `stableDownload()` 带 30s 超时 + CDN URL 刷新 + 重试 |

---

## 7. 前端问题汇总

### 🔴 问题 1：`pollBatchStatus()` 缺少 `partial_done` 终止条件

| 项目 | 详情 |
|------|------|
| **文件** | `frontend/api/client.ts` |
| **位置** | 行 734 |
| **现状** | `if (d?.status === "done" \|\| d?.status === "failed" \|\| r.code !== 0) return r;` |
| **问题** | 如果后端 P1.1 返回 `"partial_done"`，轮询器不会停止 → 无限循环 |
| **影响** | B台按钮永久禁用 + 进度条卡死 + 持续请求后端 |
| **建议修复** | 终止条件增加 `"partial_done"` |

### 🟡 问题 2：`BatchStatus` 类型缺少 `partial_done`

| 项目 | 详情 |
|------|------|
| **文件** | `frontend/api/client.ts` |
| **位置** | 行 700 |
| **现状** | `status: "queued" \| "running" \| "done" \| "failed"` |
| **问题** | TypeScript union type 不包含 `"partial_done"` |
| **影响** | 运行时不报编译错误（JSON 不受 TS 约束），但逻辑不完整 |
| **建议修复** | union type 增加 `"partial_done"` |

### 🟡 问题 3：`handleBClick` 的 partial_done 分支不刷新陈列面

| 项目 | 详情 |
|------|------|
| **文件** | `frontend/pages/Workbench.tsx` |
| **位置** | 行 430-441 |
| **现状** | 仅 `status === "done"` 时执行 `loadViral()` + 滚动 |
| **问题** | `partial_done` 走 else 分支，只显示 toast，不刷新视频列表 |
| **影响** | 用户看到 toast "裂变结束: partial_done" 但陈列面不更新 |
| **建议修复** | partial_done 也执行 loadViral + 滚动（部分成功也应展示已完成的视频） |

### ⚪ 非问题确认

| 项目 | 说明 |
|------|------|
| 14 秒卡死 | 后端 PTS 问题，前端 `window.open()` 无法控制 |
| A台 preview | 端点独立，不受 P1.1 影响 |
| A台 compose 4031 | 逻辑完整保持 |
| MD5 重复 | 纯后端问题，前端无感知 |
| 视频空白卡片 | 三级 fallback 完整 |
| 分页异常 | PAGE_SIZE=50，30 条不触发分页 |

---

## 8. 需要前端代码小修 — 文件清单

| # | 文件 | 改动点 | 原因 | 优先级 |
|---|------|--------|------|--------|
| 1 | `frontend/api/client.ts` 行 700 | `BatchStatus.status` union type 增加 `"partial_done"` | 类型完整性 | P1 |
| 2 | `frontend/api/client.ts` 行 734 | `pollBatchStatus()` 终止条件增加 `d?.status === "partial_done"` | **防止无限轮询** | P0 |
| 3 | `frontend/pages/Workbench.tsx` 行 432 | `handleBClick` 的 `.then()` 中 `partial_done` 也执行 `loadViral()` + 滚动 + dashboard 刷新 | 展示已完成视频 | P1 |

**预估改动量**：约 5-8 行代码变更，不涉及新文件 / 新依赖 / 新端点。

> ⚠️ **不直接改代码，先交 ChatGPT 审核确认。**

---

## 9. 操作步骤（供 staging 真实联调用）

待扣子部署完成后，按以下步骤操作：

1. 登录 staging 环境（phone + invite_code）
2. 上传 ≥ 3 个时长 ≥ 30 秒的视频
3. 确认「会话源视频池」显示正确数量和合格数量
4. 点击「B台·裂变」按钮
5. 观察进度条 + 计数是否实时更新
6. 等待裂变完成（观察是否出现 partial_done）
7. 确认 30 条（或实际数量）viral 视频展示
8. 逐个点击播放，确认能播放到结尾（PTS 修复验证）
9. 检查是否有空白卡片 / 重复卡片
10. 切换到 A台，点击「预览导演稿」确认正常
11. 点击「A台·生成母视频」确认仍显示 4031 维护态
12. 截图记录各步骤现象

---

## 10. 禁止事项确认

| 禁止项 | 状态 |
|--------|------|
| 不改后端 | ✅ 未触碰 |
| 不改接口协议 | ✅ 仅审查前端兼容性 |
| 不接真实火山 | ✅ 未配置 |
| 不解锁 compose | ✅ 4031 逻辑保持 |
| 不碰 production | ✅ 仅代码审查 |
| 不自行部署 | ✅ 未执行部署 |
| 不扩大到 P2 中间层 | ✅ 仅审查 P1.1 范围 |

---

## 附录：审查文件清单

| 文件 | 行数 | 审查轮次 |
|------|------|----------|
| `frontend/api/client.ts` | 806 | P0-B 开发 + P1.1 验收 |
| `frontend/pages/Workbench.tsx` | 935 | P0-B 开发 + P1.1 验收 |
| `frontend/styles.css` | 1404 | P0-B 开发（本轮无变更） |
| `frontend/pages/AdminPanel.tsx` | 357 | P1 验证（本轮无变更） |
| `FRONTEND_V4_CURRENT_API_CONTRACT.md` | 219 | 接口合同唯一真源 |
