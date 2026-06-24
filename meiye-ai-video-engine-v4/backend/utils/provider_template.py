"""真实视频 Provider 接入模板（复制改造用）。

⚠️ 这是模板，不是可用实现：端点 / 请求体 / 鉴权 / 响应字段都要按你的厂商
（可灵 / 即梦 / Runway / 火山）API 文档填。填好后在 video_provider._PROVIDERS 注册。

绝大多数视频生成 API 都是异步：提交任务拿 job_id → 轮询拿 mp4_url。
HTTPVideoProvider 已实现轮询/超时/兜底，子类只需实现 _submit / _poll。
"""

from __future__ import annotations

import httpx

from utils.video_provider import HTTPVideoProvider, ProviderError


class ExampleVendorProvider(HTTPVideoProvider):
    name = "example_vendor"

    def _headers(self) -> dict:
        # TODO: 按厂商鉴权方式调整（Bearer / API-Key header / 签名等）
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _submit(self, prompt: str, params: dict) -> str:
        # TODO: 换成厂商「提交生成任务」端点与请求体
        resp = httpx.post(
            f"{self.api_base}/v1/video/generate",
            headers=self._headers(),
            json={"prompt": prompt, **params},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        job_id = data.get("job_id") or data.get("task_id")
        if not job_id:
            raise ProviderError(f"submit 未返回 job_id: {data}")
        return job_id

    def _poll(self, job_id: str) -> tuple[str, str | None]:
        # TODO: 换成厂商「查询任务」端点与响应字段映射
        resp = httpx.get(
            f"{self.api_base}/v1/video/tasks/{job_id}",
            headers=self._headers(),
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        # TODO: 把厂商状态值映射到 pending/running/done/failed
        status = data.get("status", "running")
        url = data.get("video_url") or data.get("result", {}).get("url")
        return status, url


# 注册（在 video_provider._PROVIDERS 里加一行）：
#   from utils.provider_template import ExampleVendorProvider
#   _PROVIDERS["example_vendor"] = ExampleVendorProvider
# 然后 .env：VIDEO_PROVIDER=example_vendor / VIDEO_API_BASE=... / VIDEO_API_KEY=...
