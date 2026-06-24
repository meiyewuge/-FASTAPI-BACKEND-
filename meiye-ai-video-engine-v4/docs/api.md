# API 列表 · api.md

统一前缀 `/api`。统一响应包 `{ "code": 0, "msg": "ok", "data": ... }`，`code != 0` 为错误。
租户：请求头 `X-Tenant-Id`（缺省 = `default`）。视频生成异步：提交返回 `task_id`，轮询任务状态。

> 实现状态：✅ 全部可运行（默认 Mock 视频 provider）。接真实视频 provider 见 `backend/utils/video_provider.py`。

## 鉴权
| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/auth/login` | 手机号/token 登录，返回 `{token, tenant_id}` |

```jsonc
// POST /api/auth/login
{ "phone": "13800000000" }          // 或 { "token": "..." }
→ { "code":0, "data": { "token":"tk_default", "tenant_id":"default" } }
```

## Intent Layer · 业务理解层（一句话入口）
轻量规则解析（无 LLM）。门店是 tenant 内 target，**不拆 tenant**。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/intent/plan` | 仅解析：一句话 → 结构化 Intent（不落库） |
| POST | `/api/generate` | 统一入口：解析 → 多门店拆单 → 自动建并分派任务 |
| GET  | `/api/stores` | 当前租户门店列表 |

```jsonc
// POST /api/intent/plan
{ "text": "帮我做10个广州美容院抗衰视频" }
→ { "code":0, "data": {
     "action":"generate_video_batch", "count":10, "city":"广州",
     "industry":"美容院", "theme":"抗衰",
     "target_type":"store", "tenant_scope":"current_tenant" } }

// POST /api/generate （仍属 1 个 tenant；10 门店 = 10 个 target）
{ "text": "帮我做10个广州美容院抗衰视频" }
→ { "code":0, "data": {
     "intent": { ... },
     "plan": { "count":10, "target_type":"store",
               "store_ids":[1..10], "task_ids":["...", ...] } } }
// 批量成本超配额：{ "code":4029, "msg":"...成本熔断..." }
```

## A台 · 母视频
| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/a/generate` | 一句话 → 母视频（异步） |

```jsonc
// POST /api/a/generate
{ "prompt": "给轻医美门店做一条招商视频", "title": "可选" }
→ { "code":0, "data": { "task_id": "..." } }
// 成本超配额时：{ "code":4029, "msg":"...成本熔断..." }
```

## B台 · 混剪裂变（商业内容生成器）
内容策略分型（引流型/成交型/IP型/招商型/获客型）+ 情绪结构 4 拍 + 门店差异化。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/b/generate` | 母视频 → 批量裂变（异步，10~50 条，可选策略） |
| GET  | `/api/b/strategies` | 可选内容策略列表（供前端选择） |

```jsonc
// POST /api/b/generate
{ "source_video_id": 1, "count": 20,
  "strategy": "mix",            // mix(轮换5型) | 引流型 | 成交型 | IP型 | 招商型 | 获客型
  "prompt": "可选主题" }
→ { "code":0, "data": { "task_id": "..." } }

// 任务结果中每条裂变带 strategy + store_id（门店归因），
// meta.changes 含 structure(情绪结构4拍) 与 store_version(如「广州版」)

// GET /api/b/strategies
→ { "code":0, "data": { "items": [
     { "key":"引流型", "label":"引流型", "goal":"涨粉引流", "cta":"关注解锁更多干货" }, ... ] } }
```

## 任务
| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET  | `/api/tasks/{task_id}` | 查询任务（pending/running/done/failed + result） |
| GET  | `/api/tasks` | 当前租户任务列表 |
| POST | `/api/tasks/{task_id}/retry` | 重试（仅 failed 任务） |

```jsonc
// GET /api/tasks/{task_id}
→ { "code":0, "data": {
      "task_id":"...", "type":"a", "status":"done", "progress":1.0,
      "retry_count":0,
      "result": { "videos":[ { "video_id":1, "type":"mother",
                  "download_url":"...", "share_url":"..." } ] },
      "error": null } }
```

## 历史视频
| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/videos?type=mother\|viral&page=1&page_size=20` | 视频列表，按租户隔离 |

## 成本
| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/cost/summary` | 当前租户：配额/已花/剩余/分项 |
| GET | `/api/cost/by-store` | 门店级成本报表（每门店：视频数/时长/成本）|
| GET | `/api/cost/by-provider` | 按 provider 聚合成本 |

```jsonc
// GET /api/cost/by-store
→ { "code":0, "data": { "items": [
     { "store_id":1, "store_name":"广州医美1", "records":3, "videos":3,
       "duration_sec":41.0, "cost":1.2 }, ... ] } }
```

```jsonc
→ { "code":0, "data": {
      "tenant_id":"default", "quota":100.0, "spend":1.5, "remaining":98.5,
      "by_api": { "video.generate.a":1.0, "video.remix.b":0.5 } } }
```

## 业务指标（成本侧推导，无收入/ROI 假设）
| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/metrics/overview` | 内容效率：产出/成本/每元产出视频数/裂变倍率 |
| GET | `/api/metrics/by-store` | 门店产能与成本效率 |
| GET | `/api/metrics/by-strategy` | 各内容策略产出条数与成本占比 |

```jsonc
// GET /api/metrics/overview
→ { "code":0, "data": {
     "total_videos":13, "mother_videos":3, "viral_videos":10, "total_cost":4.0,
     "avg_cost_per_video":0.3077, "videos_per_cost_unit":3.25, "remix_multiplier":3.33 } }
```
> 仅成本侧客观指标；收入/ROI/分润/定价需业务口径，不在此层。

## 其它
| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 健康检查 |
| GET | `/api/info` | 服务信息（当前 provider/env） |
| GET | `/docs` | Swagger 文档（自动） |

## 错误码
| code | 含义 |
| --- | --- |
| 0 | 成功 |
| 2001 | 参数错误（如非失败任务重试） |
| 3001 | 任务不存在 |
| 4029 | 成本熔断（超配额） |
