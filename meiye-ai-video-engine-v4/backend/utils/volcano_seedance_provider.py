"""火山方舟 Doubao Seedance 2.0 真实视频 Provider（生产级）。

接口（用户已确认）：
  提交：POST {base}/api/v3/contents/generations/tasks
  查询：GET  {base}/api/v3/contents/generations/tasks/{task_id}
  鉴权：Authorization: Bearer <API_KEY>
  模型：doubao-seedance-2.0-260128

只扩展 provider 层；上层（intent/orchestrator/store/A·B engine）不受影响。
失败由上层 FallbackProvider 兜底（volcano → retry → mock）。
"""

from __future__ import annotations

import httpx

from config import settings
from utils.video_provider import HTTPVideoProvider, ProviderError

_DEFAULT_BASE = "https://ark.cn-beijing.volces.com"

# 火山任务状态 → 统一状态
_STATUS_MAP = {
    "queued": "pending",
    "pending": "pending",
    "running": "running",
    "processing": "running",
    "succeeded": "done",
    "success": "done",
    "failed": "failed",
    "cancelled": "failed",
    "canceled": "failed",
    "expired": "failed",
}


class VolcanoSeedanceProvider(HTTPVideoProvider):
    name = "volcano_seedance"

    def __init__(self) -> None:
        super().__init__()
        self.base = (self.api_base or _DEFAULT_BASE).rstrip("/")
        self.model = settings.volcano_model

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _submit(self, prompt: str, params: dict) -> str:
        resp = httpx.post(
            f"{self.base}/api/v3/contents/generations/tasks",
            headers=self._headers(),
            json={"model": self.model, "content": [{"type": "text", "text": prompt}]},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        task_id = data.get("id") or data.get("task_id")
        if not task_id:
            raise ProviderError(f"火山提交未返回 task_id: {data}")
        return task_id

    def _poll(self, task_id: str) -> tuple[str, str | None]:
        resp = httpx.get(
            f"{self.base}/api/v3/contents/generations/tasks/{task_id}",
            headers=self._headers(),
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        raw_status = (data.get("status") or "running").lower()
        status = _STATUS_MAP.get(raw_status, "running")
        # 兼容几种返回结构里 video_url 的位置
        content = data.get("content") or {}
        url = (
            data.get("video_url")
            or content.get("video_url")
            or (content.get("video") or {}).get("url")
        )
        return status, url
