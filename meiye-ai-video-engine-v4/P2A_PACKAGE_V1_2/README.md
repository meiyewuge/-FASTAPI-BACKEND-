# QODER_V4_P2A_FRONTEND_MINIMAL_PREVIEW_WORKBENCH_V1_2

## 包信息

| 项目 | 值 |
|------|-----|
| 包名 | QODER_V4_P2A_FRONTEND_MINIMAL_PREVIEW_WORKBENCH_V1_2_20260627.zip |
| 版本 | V1.2 |
| 分支 | qoder/v4-frontend-workbench |
| 最新 Commit | c3c30ab |
| 基线 Commit | b0e0741 (V4 P0-B + P1) |
| 日期 | 2026-06-27 |
| 定位 | Preview Only — 不执行真实裂变 |

## Commit 历史（P2A 相关）

| Commit | 说明 |
|--------|------|
| 86f31e1 | V4 P2A V1.0 — 初始 Preview Workbench |
| fe40e93 | V4 P2A V1.1 — variants 结构 + skill_sequence 类型修复 |
| c3c30ab | V4 P2A V1.2 — scenario 标准 7 项 + 完整交付包 |

## 修改文件清单

| 文件路径 | 操作 | 说明 |
|----------|------|------|
| frontend/api/client.ts | 修改 | +146 行 P2A 类型定义 + 5 API 函数 |
| frontend/pages/P2APreviewWorkbench.tsx | 新建 | 497 行 P2A 预览工作台页面 |
| frontend/pages/Workbench.tsx | 修改 | +1 行 P2A 导航按钮 |
| frontend/main.tsx | 修改 | +10 行 /p2a-preview 路由 |
| frontend/styles.css | 修改 | +383 行 P2A 样式 |

## 包结构

```
P2A_PACKAGE_V1_2/
├── changed_files/
│   └── frontend/
│       ├── api/
│       │   └── client.ts          ← P2A 类型 + API（完整源码）
│       ├── pages/
│       │   ├── P2APreviewWorkbench.tsx  ← P2A 页面（完整源码）
│       │   └── Workbench.tsx           ← 含 P2A 入口（完整源码）
│       ├── main.tsx               ← 路由注册（完整源码）
│       └── styles.css             ← P2A 样式（完整源码）
├── test_outputs/
│   ├── self_test_results.txt      ← 20 项自测结果
│   ├── tsc_no_emit.txt            ← TypeScript 编译结果
│   └── vite_build.txt             ← Vite 构建结果
├── patch.diff                     ← 累计 diff (b0e0741..c3c30ab, 5 files)
├── git_log.txt                    ← P2A 相关 commit
├── SECURITY_NOTE.md               ← 安全确认
└── README.md                      ← 本文件
```

## P2A 5 个 API（Preview Only）

| # | 方法 | 路径 | 用途 |
|---|------|------|------|
| 1 | POST | /api/production-orders/preview | 生产单预览 |
| 2 | POST | /api/production-orders | 创建生产单 |
| 3 | GET  | /api/production-orders/{id} | 查询正式生产单（二次确认） |
| 4 | POST | /api/fission-plans/preview | 裂变计划预览 |
| 5 | GET  | /api/skills | 技能列表（只读） |

## 页面入口

- 登录后进入工作台 → header 区域「📋 P2A 预览」按钮
- 路由：`/#/p2a-preview`（Hash 路由）
- RequireAuth 包裹

## 页面结构

1. 黄色 Preview Only 横幅（固定顶部）
2. Step 1：输入导演稿 ID + scenario 下拉（7 项）+ platform 下拉（4 项）→ API 1
3. Step 2：生产单 Preview + shot_maps 表格 → API 2 + API 3（二次确认）
4. Step 3：裂变计划 Preview — 6 组策略 + 30 条 variant 表格（可展开）
5. Skills 只读面板（API 5）

## scenario 标准值

| 值 | 中文 |
|----|------|
| product_seeding | 产品种草 ← 默认 |
| brand_story | 品牌故事 |
| tutorial | 教程 |
| comparison | 对比评测 |
| review | 体验测评 |
| event | 活动宣传 |
| testimony | 用户证言 |

## 回滚说明

回滚到 P2A 之前：
```bash
git checkout b0e0741 -- frontend/api/client.ts frontend/pages/Workbench.tsx frontend/main.tsx frontend/styles.css
git rm frontend/pages/P2APreviewWorkbench.tsx
```

回滚到 V1.1：
```bash
git checkout fe40e93 -- frontend/
```

回滚到 V1.0：
```bash
git checkout 86f31e1 -- frontend/
```

## 部署前提

- [ ] ChatGPT 审核通过
- [ ] 扣子组织终审
- [ ] 部署到 staging（非 production）
- [ ] 真实浏览器 Network 证据补充
