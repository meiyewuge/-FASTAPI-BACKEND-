# 前端对接契约（给 Qoder）· frontend_contract.md

> 后端已实现并测试。本文件是**前端对接说明书**：页面结构、用户流程、API 绑定、数据流。
> 后端=Claude，前端 UI=Qoder。下列每个端点均真实存在（见 `docs/api.md` / `backend/api/routes.py`）。

## 0. 极简原则（V4.0 铁律）
前端只有 **2 个页面**：**登录页** + **唯一工作台**。
工作台 = `一个输入框 + 两个按钮（A台/B台）+ 状态区 + 历史列表 + 成本面板`。
所有复杂能力（tenant/成本/队列/模型/策略）都在后端，前端不暴露。

---

## 1. 通用约定
- BaseURL：`/api`
- 统一响应包：`{ "code": 0, "msg": "ok", "data": ... }`；`code !== 0` 即错误，`msg` 可直接提示。
- **租户头**：登录拿到 `tenant_id` 后，**所有请求带** `X-Tenant-Id: <tenant_id>`。
  （当前鉴权为占位：后端用该头解析租户；真实 JWT 校验为后续 TODO，前端先按此对接。）
- 视频生成是**异步**：提交得 `task_id` → 轮询任务状态 → `done` 后取 `result.videos`。

### 错误码
| code | 含义 | 前端处理 |
| --- | --- | --- |
| 0 | 成功 | - |
| 2001 | 参数错误 | 提示 msg |
| 3001 | 任务不存在 | 停止轮询 |
| 4029 | 成本熔断（超配额）| 弹窗：配额不足，msg 有详情 |

---

## 2. 页面与用户路径

### 页面 A：登录页
```
[手机号/token 输入] → [进入系统]
  → POST /api/auth/login → 存 token + tenant_id（本地）→ 跳工作台
```

### 页面 B：工作台（唯一核心页）
```
┌─────────────────────────────────────────────┐
│ 美业AI视频系统 V4.0            [成本面板:剩余¥]│
│ [ 请输入视频需求 ........................... ] │
│ [🎬 生成母视频(A台)]  [🔁 生成裂变(B台)]       │
│ 任务状态：进行中 / 已完成 / 可下载 / 可分发     │
│ 历史：[母视频列表] [裂变视频列表]              │
└─────────────────────────────────────────────┘
```

**主流程（一句话批量，推荐入口）**
```
输入一句话（"帮我做10个广州美容院抗衰视频"）
 → POST /api/generate
 → 拿到 plan.task_ids[]（多门店拆单，仍属 1 租户）
 → 轮询每个 GET /api/tasks/{id} 至 done
 → 渲染母视频列表 + 更新成本面板
```

**B台裂变流程**
```
在某条母视频上点"裂变"
 → 选策略（GET /api/b/strategies）
 → POST /api/b/generate { source_video_id, count, strategy }
 → 轮询 task → done → 渲染裂变列表（每条带 strategy + 门店版本）
```

---

## 3. API 绑定清单（前端需要的全部端点）

### 3.1 登录
`POST /api/auth/login`
```jsonc
req:  { "phone": "13800000000" }          // 或 { "token": "..." }
resp: { "code":0, "data": { "token":"tk_default", "tenant_id":"default" } }
```

### 3.2 一句话生成（统一入口，A台批量）
`POST /api/generate`
```jsonc
req:  { "text": "帮我做10个广州美容院抗衰视频" }
resp: { "code":0, "data": {
         "intent": { "count":10, "city":"广州", "industry":"美容院", "theme":"抗衰", ... },
         "plan": { "count":10, "target_type":"store",
                   "store_ids":[1..10], "task_ids":["...", ...] } } }
```
（仅解析不执行：`POST /api/intent/plan { text }` → 返回 intent，用于"预览理解结果"。）

### 3.3 A台 / B台（单条入口，可选）
`POST /api/a/generate`  → `req { prompt, title? }` → `data { task_id }`
`POST /api/b/generate`  → `req { source_video_id, count(1~50), strategy?, prompt? }` → `data { task_id }`
`GET  /api/b/strategies` → `data.items[{ key, label, goal, cta }]`（mix/引流型/成交型/IP型/招商型/获客型）

### 3.4 任务（轮询）
`GET /api/tasks/{task_id}`
```jsonc
resp: { "code":0, "data": {
   "task_id":"...", "type":"a|b", "status":"pending|running|done|failed",
   "progress":0~1, "retry_count":0, "error":null,
   "result": { "videos": [
       { "video_id":1, "type":"mother|viral", "download_url":"...", "share_url":"...",
         "strategy":"引流型", "store_id":1 } ] } } }
```
轮询建议：1~2s 一次，`status` ∈ {done, failed} 即停。
`GET /api/tasks` 列表；`POST /api/tasks/{id}/retry` 重试（仅 failed）。

### 3.5 历史视频
`GET /api/videos?type=mother|viral&page=1&page_size=20`
```jsonc
data: { "items":[ { "video_id", "type", "title", "source_video_id",
                    "download_url", "share_url" } ], "total":123 }
```

### 3.6 门店
`GET /api/stores` → `data.items[{ store_id, name, city, industry }]`

### 3.7 成本面板
`GET /api/cost/summary` → `data { tenant_id, quota, spend, remaining, by_api }`
`GET /api/cost/by-store` → `data.items[{ store_id, store_name, videos, duration_sec, cost }]`
`GET /api/cost/by-provider` → `data.items[{ provider, records, cost }]`

### 3.8 业务指标（可选看板）
`GET /api/metrics/overview` → `{ total_videos, total_cost, videos_per_cost_unit, remix_multiplier, ... }`
`GET /api/metrics/by-store` → 门店产能/效率
`GET /api/metrics/by-strategy` → 各策略产出占比

---

## 4. 推荐前端组件 ↔ API 映射
| 组件 | API |
| --- | --- |
| 登录表单 | `/auth/login` |
| 工作台输入框 + 主按钮 | `/generate`（或 `/a/generate`）|
| 策略选择器 | `/b/strategies` → `/b/generate` |
| 任务状态区 | 轮询 `/tasks/{id}` |
| 母/裂变视频列表 | `/videos?type=` |
| 成本面板 | `/cost/summary`（顶部剩余额度）|
| 数据看板（可选）| `/metrics/*`、`/cost/by-store` |

## 5. 前端 API 客户端
`frontend/api/client.ts` 已按本契约提供绑定函数，Qoder 可直接用或参照改造。

## 6. 本地联调
```bash
# 后端
cd backend && pip install -r requirements.txt && uvicorn main:app --reload   # :8000/docs
# 前端 vite 代理 /api → :8000（见 frontend/vite.config.ts）
```
默认 Mock provider 即可跑通整条 UI 流程（产出占位 mp4 链接）；接火山真实视频见 `docs/provider.md`。
