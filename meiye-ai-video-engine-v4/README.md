# 美业AI视频系统 V4.0 · meiye-ai-video-engine-v4

> 把一个「AI 视频工业系统」压缩成 **一个按钮**。
> 这不是后台系统、不是管理平台、不是运营工具 —— 而是一台 **一键视频工厂（AI Content Machine）**。

本仓库是面向 **SaaS 多租户** 的标准分层代码库。结构从第一天起就是 SaaS 结构，**不允许随意更改**。

---

## 两个核心能力入口

| 入口 | 名称 | 作用 |
| --- | --- | --- |
| 🎬 A台 | 生产母视频 | 输入一句话 → AI 生成脚本 → 调用视频生成 → 输出 1 条精品母视频（IP/招商/课程） |
| 🔁 B台 | 混剪裂变 | 选择母视频 → 自动切片 → 重组 → 改字幕/开头/结尾 → 输出 10~50 条裂变视频（门店矩阵分发） |

前端只有 **登录页 + 一个工作台**。所有复杂功能（tenant_id、成本统计、API 日志、队列、模型选择、BGM 库、字幕模板库）**全部隐藏在后端**。

---

## 极简用户路径（3 步闭环）

1. 登录（手机号 / token，自动绑定 tenant_id）
2. 输入一句话视频需求
3. 点按钮 → A台 或 B台 → 下载 + 分发链接

---

## 代码库结构（强制执行）

```
meiye-ai-video-engine-v4/
├── backend/                # 后端（与前端物理隔离）
│   ├── a_engine/           # A台：母视频生成（独立模块）
│   ├── b_engine/           # B台：混剪裂变（独立模块）
│   ├── api/                # API 统一出口 /api/*
│   ├── services/           # 业务逻辑层
│   ├── models/             # 数据模型
│   ├── tasks/              # 任务/队列系统
│   ├── utils/              # 工具类
│   └── main.py             # FastAPI 入口
│
├── frontend/               # 前端（极简 SaaS，Qoder 接管）
│   ├── pages/              # Login + Workbench（仅两页）
│   ├── components/
│   ├── api/                # 前端 API 调用层
│   └── main.tsx
│
├── docs/                   # 架构文档
│   ├── architecture.md
│   ├── api.md
│   └── workflow.md
│
├── infra/                  # 部署
│   ├── docker-compose.yml
│   ├── nginx.conf
│   └── deploy.sh
│
└── README.md
```

## 工程铁律

> **先定 Git 结构，再写代码，而不是写代码再整理结构。**

分层原则详见 [`docs/architecture.md`](docs/architecture.md)：
1. 前后端物理隔离，禁止混写、禁止跨目录调用。
2. `a_engine` 与 `b_engine` 不共享逻辑代码，只能通过 API 调用。
3. 所有请求统一走 `/api/*`；禁止前端直连数据库、禁止引擎互调。
4. 任务系统独立模块（`backend/tasks/video_task.py`）。

## 当前状态

🟡 **脚手架阶段（skeleton）** —— 目录结构 + 架构文档 + 占位模块已就位，**尚未实现真实视频生成逻辑**。
后续按 `docs/workflow.md` 分支策略（feature/a、feature/b、feature/ui）逐步落地。
