# Qoder V4 P1.1 partial_done 前端小修报告

> **修复时间**：2026-06-24  
> **修复人**：Qoder  
> **审核来源**：ChatGPT 审核通过预验收报告后授权最小修复  
> **Commit**：`fe2ea24`（qoder/v4-frontend-workbench 分支）  
> **改动量**：2 个文件，+9 行 / -3 行

---

## 1. 问题复盘

### 背景

P1.1 Remixer 后端修复（PTS 卡死 + MD5 重复）可能引入新的 batch 终态 `"partial_done"`——表示部分视频生成成功、部分失败。前端预验收发现 3 处兼容性问题：

### 修正说明

> 预验收报告中写"3 处均在 1 个文件内"有误。实际涉及 **`client.ts` 与 `Workbench.tsx` 两个文件**，更正为：**3 处问题，涉及 2 个文件**。

### 修复前风险

| # | 文件 | 行号 | 问题 | 风险等级 |
|---|------|------|------|----------|
| 1 | `client.ts` | 700 | `BatchStatus.status` union type 不含 `"partial_done"` | P1 — 类型不完整 |
| 2 | `client.ts` | 734 | `pollBatchStatus()` 终止条件不含 `"partial_done"` → **无限轮询** | **P0 — 生产风险** |
| 3 | `Workbench.tsx` | 432 | `handleBClick` partial_done 走 else 分支，不刷新陈列面 | P1 — 用户体验 |

**无限轮询后果**：后端返回 `partial_done` 时，轮询永不停止 → `batchRunning` 永远为 `true` → B台按钮永久禁用 + 每 1.5s 持续请求后端（虽然 `onTick` 仍执行，进度条数值正确，但流程无法结束）。

---

## 2. 修改文件清单

| 文件 | 改动 | 行数变化 |
|------|------|----------|
| `frontend/api/client.ts` | 2 处：类型 union + 终止条件 | +2 / -2 |
| `frontend/pages/Workbench.tsx` | 1 处：新增 partial_done 分支 | +6 / -0 |
| **合计** | **2 个文件，3 处改动** | **+9 / -3** |

---

## 3. 修改后逻辑

### 3.1 client.ts — BatchStatus 类型（行 700）

**修改前：**
```typescript
status: "queued" | "running" | "done" | "failed";
```

**修改后：**
```typescript
status: "queued" | "running" | "done" | "failed" | "partial_done";
```

> 同步更新 `BatchGenerateResult.status`（行 684），保持一致。

### 3.2 client.ts — pollBatchStatus() 终止条件（行 734）

**修改前：**
```typescript
if (d?.status === "done" || d?.status === "failed" || r.code !== 0) return r;
```

**修改后：**
```typescript
if (d?.status === "done" || d?.status === "failed" || d?.status === "partial_done" || r.code !== 0) return r;
```

**行为保证：**
- `done` → 终止 ✅（行为不变）
- `failed` → 终止 ✅（行为不变）
- `partial_done` → **终止** ✅（新增，视为"终态但非失败"）
- `queued` / `running` → 继续轮询 ✅（行为不变）
- 不再每 1.5s 无限请求后端 ✅

### 3.3 Workbench.tsx — handleBClick partial_done 分支（行 438-443）

**修改前：**
```typescript
if (final.data?.status === "done") {
  // done 分支
} else {
  showToast(`裂变结束: ${final.data?.status || "未知"}`);
}
```

**修改后：**
```typescript
if (final.data?.status === "done") {
  // done 分支（不变）
} else if (final.data?.status === "partial_done") {
  const c = final.data.completed || 0, f = final.data.failed || 0;
  showToast(`部分视频生成成功（${c} 条），失败项已跳过（${f} 条），可先查看已生成视频。`);
  loadViral(1, batch_id);
  loadDashboard();
  setTimeout(() => viralRef.current?.scrollIntoView({ behavior: "smooth" }), 300);
} else {
  showToast(`裂变结束: ${final.data?.status || "未知"}`);
}
```

**行为保证：**
- `setBatchRunning(false)` → 三个分支共享（行 431，在 if 之前）✅
- `partial_done` → toast 提示 + `loadViral()` 刷新 + `loadDashboard()` + 滚动 ✅
- 已成功生成的视频能展示 ✅
- `failed` 项不导致页面崩溃（`final.data.failed || 0` 兜底）✅
- `done` 分支不受影响 ✅
- `failed` / 未知 分支不受影响 ✅
- A台 preview / compose 锁定逻辑不受影响 ✅

---

## 4. 测试命令与结果

### 4.1 TypeScript 类型检查

```bash
cd frontend && npx tsc --noEmit
```

**结果**：✅ 0 error / 0 warning

### 4.2 Vite 生产构建

```bash
cd frontend && npx vite build
```

**结果**：✅ built in 847ms，37 modules，0 error / 0 warning

```
dist/index.html                   0.41 kB │ gzip:  0.31 kB
dist/assets/index-CoTcTTtX.css   21.07 kB │ gzip:  4.42 kB
dist/assets/index-DPjO7364.js   243.96 kB │ gzip: 79.34 kB
```

### 4.3 逻辑验证（代码级走查）

| # | 场景 | 预期行为 | 代码验证 |
|---|------|----------|----------|
| 1 | `status=done` | 轮询停止 + toast "裂变完成" + loadViral + 滚动 | ✅ 行 432-437 不变 |
| 2 | `status=failed` | 轮询停止 + toast "裂变结束: failed" | ✅ 行 444-445 不变 |
| 3 | `status=partial_done` | 轮询停止 + toast "部分视频生成成功" + loadViral + 滚动 | ✅ 行 438-443 新增 |
| 4 | `status=queued/running` | 继续轮询（1.5s） | ✅ 不匹配任何终止条件 |
| 5 | B台按钮不永久禁用 | `setBatchRunning(false)` 在所有终态后执行 | ✅ 行 431 在 if 之前 |
| 6 | 30 条视频展示 | PAGE_SIZE=50，单页展示 | ✅ 未改动列表渲染逻辑 |
| 7 | A台 preview 不受影响 | `handlePreview()` 不依赖 batch 状态 | ✅ 未改动 |
| 8 | A台 compose 4031 锁定 | `composeMaintenance` 逻辑独立 | ✅ 未改动 |
| 9 | `r.code !== 0`（网络/接口错误） | 轮询停止 + else 分支 | ✅ 终止条件含 `r.code !== 0` |

---

## 5. 不变更确认

| 检查项 | 状态 |
|--------|------|
| 是否新增依赖 | **否** |
| 是否改接口（API 路径/请求体/响应体） | **否** |
| 是否改后端 | **否** |
| 是否触发火山 | **否** |
| 是否影响 production | **否** |
| 是否解锁 compose / 4031 | **否** |
| 是否影响 A台 preview | **否** |
| 是否影响 done 分支 | **否** |
| 是否影响 failed 分支 | **否** |

---

## 6. Git 信息

| 项目 | 值 |
|------|-----|
| 分支 | `qoder/v4-frontend-workbench` |
| Commit | `fe2ea24` |
| 父 Commit | `b0e0741`（P0-B + P1 开发） |
| 推送目标 | `origin/qoder/v4-frontend-workbench` |
| 文件变更 | `frontend/api/client.ts` + `frontend/pages/Workbench.tsx` |

---

## 7. 后续步骤

1. 本报告 + commit `fe2ea24` 交 ChatGPT 审核
2. 审核通过后等扣子完成 staging 后端部署
3. 执行真实 staging 联调验证（12 项验收点 + partial_done 场景）
4. 联调通过后合并到主分支

---

## 附录：完整 Diff

```diff
diff --git a/frontend/api/client.ts b/frontend/api/client.ts
--- a/frontend/api/client.ts
+++ b/frontend/api/client.ts
@@ -681,7 +681,7 @@
 export interface BatchGenerateResult {
   batch_id: string;
-  status: "queued" | "running" | "done" | "failed";
+  status: "queued" | "running" | "done" | "failed" | "partial_done";
   source_count: number;
@@ -698,7 +698,7 @@
 export interface BatchStatus {
   batch_id: string;
-  status: "queued" | "running" | "done" | "failed";
+  status: "queued" | "running" | "done" | "failed" | "partial_done";
   completed: number;
@@ -733,7 +733,7 @@
     if (d) onTick?.(d);
-    if (d?.status === "done" || d?.status === "failed" || r.code !== 0) return r;
+    if (d?.status === "done" || d?.status === "failed" || d?.status === "partial_done" || r.code !== 0) return r;
     await new Promise((res) => setTimeout(res, intervalMs));

diff --git a/frontend/pages/Workbench.tsx b/frontend/pages/Workbench.tsx
--- a/frontend/pages/Workbench.tsx
+++ b/frontend/pages/Workbench.tsx
@@ -437,6 +437,12 @@
           setTimeout(() => viralRef.current?.scrollIntoView({ behavior: "smooth" }), 300);
+        } else if (final.data?.status === "partial_done") {
+          const c = final.data.completed || 0, f = final.data.failed || 0;
+          showToast(`部分视频生成成功（${c} 条），失败项已跳过（${f} 条），可先查看已生成视频。`);
+          loadViral(1, batch_id);
+          loadDashboard();
+          setTimeout(() => viralRef.current?.scrollIntoView({ behavior: "smooth" }), 300);
         } else {
           showToast(`裂变结束: ${final.data?.status || "未知"}`);
```
