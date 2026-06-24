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

## B台 · 混剪裂变
| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/b/generate` | 母视频 → 批量裂变（异步，10~50 条） |

```jsonc
// POST /api/b/generate
{ "source_video_id": 1, "count": 20, "prompt": "可选" }
→ { "code":0, "data": { "task_id": "..." } }
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

```jsonc
→ { "code":0, "data": {
      "tenant_id":"default", "quota":100.0, "spend":1.5, "remaining":98.5,
      "by_api": { "video.generate.a":1.0, "video.remix.b":0.5 } } }
```

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
