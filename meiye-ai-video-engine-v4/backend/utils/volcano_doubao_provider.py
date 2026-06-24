"""火山方舟 Doubao Seedance 2.0 真实视频 Provider（生产级）。

接口（已确认）：
  提交：POST {base}/api/v3/contents/generations/tasks  body {model, content:[{type:text,text:prompt}]}
  查询：GET  {base}/api/v3/contents/generations/tasks/{task_id}  → status + video_url
  模型：doubao-seedance-2.0-260128

鉴权可切换（VOLC_AUTH_MODE）：
  bearer（默认）：Authorization: Bearer <VIDEO_API_KEY>  —— Ark /api/v3 实际用这个
  aksk          ：VOLC_AK/VOLC_SK + HMAC-SHA256 V4 签名（utils.auth_sign）

只扩展 provider 层；intent/orchestrator/store/A·B engine 不受影响。
密钥仅从环境读取，绝不硬编码 / 不打印 / 不入响应。
"""

from __future__ import annotations

import json

import httpx

from config import settings
from utils import auth_sign
from utils.video_provider import HTTPVideoProvider, ProviderError

_DEFAULT_BASE = "https://ark.cn-beijing.volces.com"

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


class VolcanoDoubaoProvider(HTTPVideoProvider):
    name = "volcano_seedance"  # cost.provider 记此值

    def __init__(self) -> None:
        super().__init__()
        self.base = (self.api_base or _DEFAULT_BASE).rstrip("/")
        self.model = settings.volc_model
        self.auth_mode = settings.volc_auth_mode

    def _auth_headers(self, method: str, url: str, body: bytes) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.auth_mode == "aksk":
            headers.update(
                auth_sign.signed_headers(
                    method, url, body, settings.volc_ak, settings.volc_sk,
                    settings.volc_region, settings.volc_service,
                )
            )
        else:  # bearer（默认）
            headers["Authorization"] = f"Bearer {settings.video_api_key}"
        return headers

    def _submit(self, prompt: str, params: dict) -> str:
        url = f"{self.base}/api/v3/contents/generations/tasks"
        body = json.dumps(
            {"model": self.model, "content": [{"type": "text", "text": prompt}]}
        ).encode("utf-8")
        resp = httpx.post(url, headers=self._auth_headers("POST", url, body), content=body, timeout=30.0)
        resp.raise_for_status()
        data = resp.json()
        task_id = data.get("id") or data.get("task_id")
        if not task_id:
            raise ProviderError(f"火山提交未返回 task_id: {data}")
        return task_id

    def _poll(self, task_id: str) -> tuple[str, str | None, float | None]:
        url = f"{self.base}/api/v3/contents/generations/tasks/{task_id}"
        resp = httpx.get(url, headers=self._auth_headers("GET", url, b""), timeout=30.0)
        resp.raise_for_status()
        data = resp.json()
        status = _STATUS_MAP.get((data.get("status") or "running").lower(), "running")
        content = data.get("content") or {}
        url_out = (
            data.get("video_url")
            or content.get("video_url")
            or (content.get("video") or {}).get("url")
        )
        duration = data.get("duration") or content.get("duration")
        return status, url_out, duration
