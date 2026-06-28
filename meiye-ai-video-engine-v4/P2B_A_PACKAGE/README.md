# QODER_V4_P2B_A_FRONTEND_MINIMAL_PREVIEW_WORKBENCH

## 包信息

| 项目 | 值 |
|------|-----|
| 版本 | V1.0 |
| 分支 | qoder/v4-frontend-workbench |
| Commit | 5d31ce2 |
| 基线 | c3c30ab (P2A V1.2) |
| 日期 | 2026-06-28 |
| 定位 | Preview Only — 后期制作脑子预览，不执行视频 |

## 修改文件清单

| 文件路径 | 操作 | 说明 |
|----------|------|------|
| frontend/api/client.ts | 修改 | +139 行 P2B-A 类型 + 8 API 函数 |
| frontend/pages/P2BPreviewWorkbench.tsx | 新建 | 440 行 P2B-A 预览工作台 |
| frontend/pages/Workbench.tsx | 修改 | +1 行 P2B-A 导航按钮 |
| frontend/main.tsx | 修改 | +10 行 /p2b-preview 路由 |
| frontend/styles.css | 修改 | +191 行 P2B-A 样式 |

## 包结构

```
P2B_A_PACKAGE/
├── changed_files/
│   └── frontend/
│       ├── api/client.ts
│       ├── pages/P2BPreviewWorkbench.tsx
│       ├── pages/Workbench.tsx
│       ├── main.tsx
│       └── styles.css
├── test_outputs/
│   ├── self_test_results.txt
│   ├── tsc_no_emit.txt
│   └── vite_build.txt
├── patch.diff
├── git_log.txt
├── SECURITY_NOTE.md
└── README.md
```

## 5 步流程

1. 选择生产单（手动输入 + 快捷按钮 + GET /production-orders/{id}）
2. 中心思想（POST /p2b/theme-kernels → 7 字段 + 锁定）
3. 预览 30 条（POST /p2b/execution-plans/preview → 6×5 网格 + 展开详情）
4. 确认入库（POST /p2b/execution-plans → 幂等处理）
5. 查看已入库（GET by-production-order + explain）

## Network 白名单

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | /production-orders/{id} | 读取生产单（复用 P2A） |
| POST | /p2b/theme-kernels | 中心思想 |
| POST | /p2b/execution-plans/preview | 预览 30 条 |
| POST | /p2b/execution-plans | 确认入库 |
| GET | /p2b/execution-plans/{id} | 查询单条 |
| GET | /p2b/execution-plans/{id}/explain | explain 说明 |
| GET | /p2b/execution-plans/by-production-order/{id} | 已入库列表 |
| GET | /p2b/skills | L2 技能列表 |

## 回滚说明

```bash
# 回滚 P2B-A
git checkout c3c30ab -- frontend/api/client.ts frontend/pages/Workbench.tsx frontend/main.tsx frontend/styles.css
git rm frontend/pages/P2BPreviewWorkbench.tsx
```
