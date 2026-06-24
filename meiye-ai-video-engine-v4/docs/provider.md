# 真实视频 Provider 接入 · provider.md

上层（A台/B台/orchestrator）只认 `VideoProvider` 统一接口，接真实厂商不影响上层。

## 架构
```
A台 generate_mother / B台 remix
        ↓ (统一接口 VideoProvider)
   get_provider()
        ↓
  FallbackProvider([ 真实provider, MockVideoProvider ])   ← 真实失败自动兜底，生产不中断
        ↓
  HTTPVideoProvider 子类（异步：提交→轮询→取 mp4）
```

- `VideoProvider`：统一接口（`backend/utils/video_provider.py`）。
- `HTTPVideoProvider`：真实厂商基类，已实现轮询/超时/兜底，子类只写 `_submit` / `_poll`。
- `FallbackProvider`：按序兜底（主 → 备 → mock），实现 fallback 机制。
- `MockVideoProvider`：默认 + 最终兜底。

## 接入步骤（可灵 / 即梦 / Runway / 火山）
1. 复制 `backend/utils/provider_template.py` 的 `ExampleVendorProvider`，按厂商 API 文档填：
   - `_headers()`：鉴权方式
   - `_submit()`：提交生成任务的端点 + 请求体 → 返回 `job_id`
   - `_poll()`：查询任务端点 + 状态/URL 字段映射（状态映射到 `pending/running/done/failed`）
2. 在 `video_provider._PROVIDERS` 注册：`_PROVIDERS["keling"] = KelingProvider`。
3. 配置 `.env`：
   ```
   VIDEO_PROVIDER=keling
   VIDEO_API_BASE=https://...
   VIDEO_API_KEY=sk-...
   VIDEO_FALLBACK=true      # 失败回退 mock
   PROVIDER_TIMEOUT=120
   POLL_INTERVAL=3
   ```
4. 重启即生效，A台/B台自动产真实视频，Mock 降级为兜底。

## 成本
provider 返回 `cost: {units, amount}`，由 `cost_service` 按 tenant 记账并参与配额熔断。
真实厂商可在子类里按 API 响应或计费规则填真实 `amount`。

## 我需要你提供的（接真实厂商所需）
- 厂商名称（可灵/即梦/Runway/火山/其它）
- API Base URL + 鉴权方式 + Key
- 「提交生成」「查询任务」两个端点的请求/响应示例（或官方文档链接）
- 计费规则（每条/每秒多少钱）—— 用于真实成本记账

给齐后我就能把 `ExampleVendorProvider` 落成你厂商的真实适配器并联调。
