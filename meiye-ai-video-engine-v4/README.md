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

## 后端快速启动

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # 默认 SQLite + Mock provider，零依赖即可跑
uvicorn main:app --reload     # http://127.0.0.1:8000/docs
```

最小闭环验证：
```bash
curl -X POST localhost:8000/api/a/generate -H 'Content-Type: application/json' -d '{"prompt":"门店招商视频"}'
curl localhost:8000/api/tasks/<task_id>      # status=done 后含 video
curl localhost:8000/api/cost/summary         # 成本统计
```

## 压测 / 产能验证（Phase 6）

```bash
cd backend
python -m load_test.load_test_runner               # 默认 100 A台 + 500 B台 / 10租户 / 50门店
python -m load_test.load_test_runner --fail-rate 0.5  # 注入失败率，验证 fallback
# 报告：load_test/reports/{metrics_report.json, load_test_summary.md, cost_analysis.csv}
```
产出：成功率 / 延迟(p50/p95/p99) / 吞吐 / 单视频·单门店·单租户成本 / fallback触发率 / 产能估算。
最近一轮（50% 注入失败）：2600 视频 / 14.8s，成功率 100%，fallback 6.7%。

## 当前状态

🟢 **后端地基可运行** —— Intent层/A台/B台/任务系统/成本系统/API 全部跑通（默认 Mock 视频 provider）：
- **Intent 层**（业务理解层，无 LLM）：一句话 →（数量/城市/行业/主题）→ 多门店拆单 → 自动建并分派任务
- A台：一句话 → 脚本 → 分镜 → provider → 母视频
- B台（商业内容生成器）：母视频 → 切片/重组 → 内容策略分型(引流/成交/IP/招商/获客) + 情绪结构4拍 + 门店差异化 → 10~50 条裂变视频
- 调度层 orchestrator：成本预检（熔断）+ 任务投递 + 按类型分派
- **三层模型**：tenant（客户/计费）→ store（门店/target）→ task（A/B 执行）。门店是租户内 target，**不拆 tenant**
- 多租户：所有表带 `tenant_id`，查询强制隔离
- 成本系统：按租户记录 + 配额熔断（超额返回 `code 4029`）

🟡 **待接真实能力** —— 视频生成走 Mock；**生产级 Provider 框架已就位**（统一接口 +
异步轮询基类 `HTTPVideoProvider` + `FallbackProvider` 兜底）。接真实厂商（可灵/即梦/Runway/火山）
只需照 [`docs/provider.md`](docs/provider.md) 写一个子类并切 `.env`，上层零改动；真实失败自动回退 Mock。

前端（Login + Workbench）为 skeleton，由 Qoder 接管。后续按 `docs/workflow.md` 分支策略推进。
