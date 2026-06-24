"""火山视频 Provider —— 双 Provider（一个模型 = 一套鉴权，不混用两代 API 体系）。

- VolcanoSeedanceProvider：火山方舟 Ark / Doubao Seedance 2.0，**仅 Bearer Token**（默认）。
- VolcanoLegacyProvider：火山旧 OpenAPI 体系，**AK/SK + HMAC-SHA256 签名**（legacy/可选）。

两者共用「提交→轮询→取 mp4」异步流程（HTTPVideoProvider），只在鉴权与端点上不同。
通过 VIDEO_PROVIDER 切换：volcano_seedance | volcano_legacy。默认 volcano_seedance。

只扩展 provider 层；密钥仅从 env 读，绝不硬编码/不打印/不入响应。
provider 只返回执行结果（url/duration/units），不决定金额（计价在 cost_engine）。
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


class _VolcanoBase(HTTPVideoProvider):
    """火山视频公共流程：提交/轮询/解析。子类只实现 _auth_headers。"""

    def __init__(self) -> None:
        super().__init__()
        self.base = (self.api_base or _DEFAULT_BASE).rstrip("/")
        self.model = settings.volc_model

    def _auth_headers(self, method: str, url: str, body: bytes) -> dict:
        raise NotImplementedError

    def _submit(self, prompt: str, params: dict) -> str:
        url = f"{self.base}/api/v3/contents/generations/tasks"
        content: list[dict] = [{"type": "text", "text": prompt}]
        # B台视频输入（video-to-video）：母视频 mp4 作为输入参考，含视频输入计费更省。
        # ⚠️ 字段名按火山「含视频输入」API 文档确认（image_url/video_url），ECS 联调时校准。
        source_url = params.get("source")
        if source_url:
            content.append({"type": "image_url", "image_url": {"url": source_url}})
        body = json.dumps({"model": self.model, "content": content}).encode("utf-8")
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


class VolcanoSeedanceProvider(_VolcanoBase):
    """Ark / Doubao Seedance 2.0 —— 仅 Bearer Token。"""

    name = "volcano_seedance"

    def _auth_headers(self, method: str, url: str, body: bytes) -> dict:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.video_api_key}",
        }


class VolcanoLegacyProvider(_VolcanoBase):
    """火山旧 OpenAPI 体系 —— AK/SK + HMAC-SHA256 V4 签名（legacy/可选）。"""

    name = "volcano_legacy"

    def _auth_headers(self, method: str, url: str, body: bytes) -> dict:
        headers = {"Content-Type": "application/json"}
        headers.update(
            auth_sign.signed_headers(
                method, url, body, settings.volc_ak, settings.volc_sk,
                settings.volc_region, settings.volc_service,
            )
        )
        return headers
