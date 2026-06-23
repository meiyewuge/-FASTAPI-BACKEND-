# API 设计 · api.md

所有接口统一前缀 `/api`。鉴权通过 `Authorization: Bearer <token>`，后端据此解析 `tenant_id`。
本文件为 **契约草案（skeleton）**，字段会在实现阶段细化。

## 约定

- 统一响应包：`{ "code": 0, "msg": "ok", "data": {...} }`，`code != 0` 表示错误。
- 视频生成为异步：提交后返回 `task_id`，前端轮询任务状态。
- 所有列表/任务均按 `tenant_id` 隔离。

## 1. 鉴权

### POST /api/auth/login
登录，自动绑定 tenant_id。
```json
// req
{ "phone": "138...", "code": "1234" }     // 或 { "token": "..." }
// resp.data
{ "token": "jwt...", "tenant_id": "t_001" }
```

## 2. A台 · 母视频

### POST /api/a/generate
输入一句话需求，生成 1 条精品母视频（异步）。
```json
// req
{ "prompt": "给做轻医美的门店做一条招商视频" }
// resp.data
{ "task_id": "task_a_..." }
```

## 3. B台 · 混剪裂变

### POST /api/b/generate
选择母视频，批量产出裂变版本（异步）。
```json
// req
{ "source_video_id": "v_001", "count": 20, "prompt": "门店矩阵分发，去重" }
// resp.data
{ "task_id": "task_b_..." }
```

## 4. 任务状态

### GET /api/tasks/{task_id}
```json
// resp.data
{
  "task_id": "task_a_...",
  "type": "a | b",
  "status": "pending | running | done | failed",
  "progress": 0.6,
  "outputs": [
    { "video_id": "v_010", "download_url": "...", "share_url": "..." }
  ]
}
```

## 5. 历史视频

### GET /api/videos?type=mother|viral&page=1
```json
// resp.data
{ "items": [ { "video_id": "...", "type": "mother", "created_at": "...", "download_url": "...", "share_url": "..." } ], "total": 123 }
```

## 错误码（草案）

| code | 含义 |
| --- | --- |
| 0 | 成功 |
| 1001 | 未登录 / token 失效 |
| 2001 | 参数错误 |
| 3001 | 任务不存在 |
| 5001 | 引擎/上游服务错误 |
