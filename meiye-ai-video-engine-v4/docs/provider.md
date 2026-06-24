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

## 已接入：火山视频（双 Provider）✅
**一个模型 = 一套鉴权，不混用两代 API 体系。** 通过 `VIDEO_PROVIDER` 切换。

| VIDEO_PROVIDER | Provider | 鉴权 | 用途 |
| --- | --- | --- | --- |
| `volcano_seedance`（默认）| VolcanoSeedanceProvider | Bearer Token | Ark / Doubao Seedance 2.0 |
| `volcano_legacy` | VolcanoLegacyProvider | AK/SK HMAC-SHA256 | 火山旧 OpenAPI 体系 |

文件：
- `utils/volcano_doubao_provider.py` —— 两个 Provider（共用提交/轮询流程）
- `utils/auth_sign.py` —— 火山 AK/SK V4 签名（legacy 用）
- `utils/video_provider_volcano.py` —— 注册实现
- `tests/test_volcano_pipeline.py` —— 全链路测试

接口（两者相同）：
- 提交 `POST {base}/api/v3/contents/generations/tasks`，body `{model, content:[{type:text,text:prompt}]}`
- 查询 `GET {base}/api/v3/contents/generations/tasks/{task_id}`，succeeded→done / failed→failed
- 模型 `doubao-seedance-2.0-260128`；兜底链 `主 → retry(3) → mock`

启用（默认走 Seedance / Bearer，推荐）：
```
VIDEO_PROVIDER=volcano_seedance
VIDEO_API_BASE=https://ark.cn-beijing.volces.com
VOLC_MODEL=doubao-seedance-2.0-260128
VIDEO_API_KEY=<ARK API Key>          # Bearer
# 旧体系才需要：VIDEO_PROVIDER=volcano_legacy + VOLC_AK / VOLC_SK
```
密钥仅入 `.env`（已 gitignore），不硬编码/不打印/不入响应。

> **计价已与 provider 解耦**：provider 只返回 `url/duration/units`，金额由 `cost_service` 统一计价。
> 换厂商/改单价只动 cost 层，不动 provider/engine。

> 验证（HTTP mock 桩）：A台/B台 e2e + 轮询 + fallback→mock + 成本(provider/store_id/duration) +
> 双 Provider 鉴权拆分 + AK/SK 签名确定性，全部通过。真实联调还需：火山密钥 + 计费单价。

## 接其它厂商（可灵/即梦/Runway…）
照 `utils/provider_template.py` 写子类，在 `video_provider._build` 或 `_PROVIDERS` 注册即可。
