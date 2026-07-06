# P2B-A Frontend Minimal Preview Workbench V1.1 Hotfix

## 包信息
- **包名**: QODER_V4_P2B_A_FRONTEND_MINIMAL_PREVIEW_WORKBENCH_V1_1_20260628.zip
- **Commit**: 6287c1e
- **分支**: qoder/v4-frontend-workbench
- **基线**: 5d31ce2 (V1.0)
- **tsc --noEmit**: PASS
- **vite build**: PASS (701ms, 39 modules)

## V1.1 修复清单

### 阻塞修复（3 项）

| # | 问题 | 修复 |
|---|------|------|
| 1 | `getAllPlans()` 不读 `data.execution_plans` | 优先读 `execution_plans` > `plans` > `groups[].plans` |
| 2 | `by-production-order` 不读 `execution_plans` | 优先读 `execution_plans` > `items` > `plans` |
| 3 | 展开详情不读 `variant_plan` 对象 + React object child 风险 | 新增 `getVariantPlan()` + `renderPlanValue()` 安全渲染 |

### 非阻塞修复（3 项）

| # | 问题 | 修复 |
|---|------|------|
| 4 | `handleReadPO` 成功后没写 `localStorage` | 新增 `setItem("p2b_last_po_id", ...)` |
| 5 | group 数量只读 `groups.length` | fallback: `Set(group_type).size` |
| 6 | `dedup_rate` 不读 `dedup_report.dedup_rate` | 兼容: `dedup_report.dedup_rate` > `dedup_rate` > "100%" |

## 真实响应兼容说明

### preview API
后端返回 `data.execution_plans: [...]` 时，前端优先读取（优先级高于 `data.plans` 和 `data.groups[].plans`）。

### by-production-order API
后端返回 `data.execution_plans: [...]` 时，Step 5 正确显示已入库计划列表。

### 展开详情
- 优先读 `p.variant_plan.rhythm_plan` 等子计划
- fallback 读 `p.rhythm_plan` 等顶层字段
- fallback 读 `p.variant_plan_json`（JSON 字符串）
- 所有值通过 `renderPlanValue()` 安全渲染：
  - `string/number/boolean` → 文本显示
  - `object` → `<pre>{JSON.stringify()}</pre>`
  - `null/undefined` → "暂无"

## 修改文件清单

| 文件 | 改动 |
|------|------|
| `frontend/api/client.ts` | +8 行（类型扩展） |
| `frontend/pages/P2BPreviewWorkbench.tsx` | +46 行（6 处修复） |

## 回滚说明
如需回滚 V1.1 → V1.0：
```bash
git revert 6287c1e
```
