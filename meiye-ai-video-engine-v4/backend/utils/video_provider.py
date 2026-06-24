"""视频生成 Provider 适配器（生产级框架）。

分层：
- VideoProvider：统一接口（A台 generate_mother / B台 remix），上层只认这个。
- MockVideoProvider：默认实现 + 最终兜底，零依赖跑通链路。
- HTTPVideoProvider：真实厂商基类（异步任务模型：提交→轮询→取 mp4），
  子类只需实现 _submit / _poll，端点/鉴权/参数按厂商文档填，上层接口不变。
- FallbackProvider：按序兜底（主 provider 失败 → 回退下一个 → 最终回退 mock），
  实现 ChatGPT 要求的 fallback 机制，保证生产不中断。

接真实厂商（可灵/即梦/Runway/火山）：写一个 HTTPVideoProvider 子类，在 _PROVIDERS 注册，
.env 设 VIDEO_PROVIDER=<name> + VIDEO_API_BASE + VIDEO_API_KEY 即可。
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

from config import settings


class ProviderError(Exception):
    """provider 生成失败（用于触发 fallback）。"""


class VideoProvider(ABC):
    name: str = "base"

    @abstractmethod
    def generate_mother(self, tenant_id: str, prompt: str, storyboard: list[str]) -> dict[str, Any]:
        """A台：生成 1 条母视频。返回 {"url","cost":{"units","amount"},...}"""

    @abstractmethod
    def remix(self, tenant_id: str, source_url: str, index: int, changes: dict) -> dict[str, Any]:
        """B台：产出第 index 条裂变视频。返回 {"url","cost":{"units","amount"},...}"""


# ---------------- Mock（默认 + 最终兜底）----------------
class MockVideoProvider(VideoProvider):
    name = "mock"

    def generate_mother(self, tenant_id: str, prompt: str, storyboard: list[str]) -> dict[str, Any]:
        slug = abs(hash((tenant_id, prompt))) % 10_000_000
        return {
            "url": f"https://mock.cdn/{tenant_id}/mother/{slug}.mp4",
            "cover": f"https://mock.cdn/{tenant_id}/mother/{slug}.jpg",
            "duration": 15 + len(storyboard),
            "cost": {"units": 1, "amount": settings.cost_per_mother},
            "meta": {"provider": self.name, "storyboard": storyboard},
        }

    def remix(self, tenant_id: str, source_url: str, index: int, changes: dict) -> dict[str, Any]:
        slug = abs(hash((source_url, index))) % 10_000_000
        return {
            "url": f"https://mock.cdn/{tenant_id}/viral/{slug}.mp4",
            "duration": 12,
            "cost": {"units": 1, "amount": settings.cost_per_clip},
            "meta": {"provider": self.name, "index": index, "changes": changes},
        }


# ---------------- 真实厂商基类（异步任务模型）----------------
class HTTPVideoProvider(VideoProvider):
    """真实 HTTP provider 基类。子类实现 _submit / _poll；本类负责轮询/超时/取 url。

    上层接口不变：generate_mother/remix 内部完成「提交→轮询→拿到 mp4」后同步返回 url。
    """

    name = "http"

    def __init__(self) -> None:
        self.api_base = settings.video_api_base
        self.api_key = settings.video_api_key
        self.timeout = settings.provider_timeout
        self.poll_interval = settings.poll_interval

    @abstractmethod
    def _submit(self, prompt: str, params: dict) -> str:
        """提交生成任务，返回厂商 job_id。按厂商文档实现。"""

    @abstractmethod
    def _poll(self, job_id: str) -> tuple[str, str | None]:
        """查询任务，返回 (status, mp4_url|None)。status ∈ {pending,running,done,failed}。"""

    def _run_job(self, prompt: str, params: dict) -> tuple[str, float | None]:
        """提交并轮询直至 done，返回 (video_url, duration)。"""
        job_id = self._submit(prompt, params)
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            res = self._poll(job_id)  # (status, url) 或 (status, url, duration)
            status, url = res[0], res[1]
            duration = res[2] if len(res) > 2 else None
            if status == "done" and url:
                return url, duration
            if status == "failed":
                raise ProviderError(f"{self.name} job {job_id} failed")
            time.sleep(self.poll_interval)
        raise ProviderError(f"{self.name} job {job_id} timeout")

    def generate_mother(self, tenant_id: str, prompt: str, storyboard: list[str]) -> dict[str, Any]:
        url, duration = self._run_job(prompt, {"type": "mother", "storyboard": storyboard})
        return {
            "url": url,
            "duration": duration,
            "cost": {"units": 1, "amount": settings.cost_per_mother},
            "meta": {"provider": self.name},
        }

    def remix(self, tenant_id: str, source_url: str, index: int, changes: dict) -> dict[str, Any]:
        url, duration = self._run_job(
            changes.get("subtitle", ""), {"type": "viral", "source": source_url, "changes": changes}
        )
        return {
            "url": url,
            "duration": duration,
            "cost": {"units": 1, "amount": settings.cost_per_clip},
            "meta": {"provider": self.name, "index": index, "changes": changes},
        }


# ---------------- Fallback 兜底链 ----------------
class FallbackProvider(VideoProvider):
    """按序尝试 providers，失败即回退下一个；全失败则抛最后异常。"""

    name = "fallback"

    def __init__(self, providers: list[VideoProvider]) -> None:
        assert providers, "fallback 需要至少一个 provider"
        self.providers = providers

    def _try(self, method: str, *args, **kwargs) -> dict[str, Any]:
        last: Exception | None = None
        for p in self.providers:
            try:
                result = getattr(p, method)(*args, **kwargs)
                result.setdefault("meta", {})["served_by"] = p.name
                return result
            except Exception as e:  # noqa: BLE001  失败回退下一个
                last = e
        raise ProviderError(f"all providers failed: {last}")

    def generate_mother(self, tenant_id: str, prompt: str, storyboard: list[str]) -> dict[str, Any]:
        return self._try("generate_mother", tenant_id, prompt, storyboard)

    def remix(self, tenant_id: str, source_url: str, index: int, changes: dict) -> dict[str, Any]:
        return self._try("remix", tenant_id, source_url, index, changes)


# provider 注册表：接真实厂商时在此登记其 HTTPVideoProvider 子类
_PROVIDERS: dict[str, type[VideoProvider]] = {
    "mock": MockVideoProvider,
    # "keling": KelingProvider,   # 子类示例见 utils/provider_template.py
    # "jimeng": JimengProvider,
    # "runway": RunwayProvider,
    # "volcano": VolcanoProvider,
}


def _build(name: str) -> VideoProvider:
    if name in ("volcano", "volcano_seedance", "volcano_doubao"):
        # 延迟导入，避免与本模块循环依赖
        from utils.video_provider_volcano import build_volcano

        return build_volcano()
    return _PROVIDERS.get(name, MockVideoProvider)()


def get_provider() -> VideoProvider:
    """构建 provider。真实 provider 链：主 →（retry N 次）→ mock 兜底，保证不中断。"""
    name = settings.video_provider
    primary = _build(name)
    if isinstance(primary, MockVideoProvider):
        return primary
    chain: list[VideoProvider] = [_build(name) for _ in range(1 + max(0, settings.provider_retries))]
    if settings.video_fallback:
        chain.append(MockVideoProvider())
    return FallbackProvider(chain)
