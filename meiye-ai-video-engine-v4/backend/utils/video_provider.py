"""视频生成 Provider 适配器（共享基础设施，A/B 引擎各自独立调用，不互相 import）。

- VideoProvider：统一接口。
- MockVideoProvider：默认实现，零依赖跑通整条链路（返回占位 URL + 成本）。
- 接入真实 provider（可灵/即梦/Runway/锐景 等）：新增一个子类实现同样方法，
  在 get_provider() 注册，并在 .env 设置 VIDEO_PROVIDER=<name> 即可，上层无需改动。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from config import settings


class VideoProvider(ABC):
    """所有视频生成 provider 的统一接口。返回值含 url + cost。"""

    name: str = "base"

    @abstractmethod
    def generate_mother(self, tenant_id: str, prompt: str, storyboard: list[str]) -> dict[str, Any]:
        """A台：根据脚本/分镜生成 1 条母视频。
        返回 {"url", "cover", "duration", "cost": {"units", "amount"}, "meta"}"""

    @abstractmethod
    def remix(self, tenant_id: str, source_url: str, index: int, changes: dict) -> dict[str, Any]:
        """B台：基于母视频产出第 index 条裂变视频。
        返回 {"url", "cost": {"units", "amount"}, "meta"}"""


class MockVideoProvider(VideoProvider):
    """占位实现：不真正渲染，返回可预测的假 URL + 成本，用于跑通链路与测试。"""

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
            "cost": {"units": 1, "amount": settings.cost_per_clip},
            "meta": {"provider": self.name, "index": index, "changes": changes},
        }


# provider 注册表：接真实 provider 时在此登记
_PROVIDERS: dict[str, type[VideoProvider]] = {
    "mock": MockVideoProvider,
    # "keling": KelingProvider,
    # "jimeng": JimengProvider,
}


def get_provider() -> VideoProvider:
    cls = _PROVIDERS.get(settings.video_provider, MockVideoProvider)
    return cls()
