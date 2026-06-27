# V4 P2A Frontend Minimal Preview Workbench

> **Commit**: `86f31e1`  
> **分支**: `qoder/v4-frontend-workbench`  
> **日期**: 2026-06-27  
> **状态**: Preview Only — 不执行真实裂变

## 概述

P2A 前端最小预览工作台，展示导演稿 → 生产单 → 裂变计划 → 30 条 variant → skill_sequence 全链路预览。

**不执行裂变，不触发火山引擎，不写 videos，不进入 production。**

## 修改文件清单

| 文件 | 操作 | 行数变化 |
|------|------|----------|
| `frontend/api/client.ts` | 修改 | +119 行（P2A 类型 + 5 API 函数） |
| `frontend/pages/P2APreviewWorkbench.tsx` | 新增 | +480 行 |
| `frontend/styles.css` | 修改 | +383 行（P2A 样式） |
| `frontend/main.tsx` | 修改 | +10 行（路由注册） |
| `frontend/pages/Workbench.tsx` | 修改 | +1 行（导航按钮） |
| **合计** | **5 文件** | **+993 行** |

## 5 个 API 端点

| # | 方法 | 路径 | 用途 |
|---|------|------|------|
| 1 | POST | `/api/production-orders/preview` | 生产单预览 |
| 2 | POST | `/api/production-orders` | 确认创建生产单 |
| 3 | GET | `/api/production-orders/{id}` | 查询正式生产单（二次确认） |
| 4 | POST | `/api/fission-plans/preview` | 裂变计划预览 |
| 5 | GET | `/api/skills` | 只读技能列表 |

## 4 步线性流程

1. **Step 1**: 输入导演稿 ID → 生成生产单 Preview
2. **Step 2**: 展示生产单 + shot_maps → 确认创建
3. **Step 3**: API 3 二次确认 → 展示正式生产单
4. **Step 4**: 裂变计划 Preview → 6 组策略 + 30 条 variant + skill_sequence

## 构建验证

```bash
npx tsc --noEmit  # ✅ 0 error
npx vite build    # ✅ 784ms, 38 modules
```

## 回滚说明

```bash
git revert 86f31e1
```

回滚将移除 P2A Preview Workbench 的所有代码，不影响 A台/B台/partial_done 逻辑。

## 禁止项

- ❌ 无 execute 按钮
- ❌ 不调 remixer
- ❌ 不调 batch-generate
- ❌ 不触发火山
- ❌ 不上传素材
- ❌ 不接付费素材
- ❌ 不写 videos
- ❌ 不做 P2B
- ❌ 不进 production
- ❌ 不硬编码 JWT/ADMIN_KEY/tenant_id
- ❌ 不引入新 UI 库
- ❌ 不引入 AGPL/OpenMontage 依赖
- ❌ 不破坏 A台/B台
- ❌ 不破坏 partial_done
