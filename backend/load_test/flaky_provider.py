"""压测用「不稳定 provider」—— 注入失败率，用于验证 fallback 触发率与稳定性。

注册名 loadtest_flaky；非 Mock，故 get_provider 会包 FallbackProvider([flaky×retry, mock])，
失败时回退 mock（served_by=mock），据此统计 fallback 触发率。仅压测用，不影响主系统。
"""

from __future__ import annotations

import os
import random
import time
from typing import Any

from utils.video_provider import _PROVIDERS, ProviderError, VideoProvider

# env: LOADTEST_FAIL_RATE(0~1) 注入失败；LOADTEST_SIM_LATENCY_MS 仿真火山 IO 延迟


class FlakyProvider(VideoProvider):
    name = "loadtest_flaky"

    @property
    def _fail_rate(self) -> float:
        try:
            return float(os.environ.get("LOADTEST_FAIL_RATE", "0"))
        except ValueError:
            return 0.0

    @property
    def _sim_latency(self) -> float:
        try:
            return float(os.environ.get("LOADTEST_SIM_LATENCY_MS", "0")) / 1000.0
        except ValueError:
            return 0.0

    def _maybe_fail(self) -> None:
        if self._sim_latency:
            time.sleep(self._sim_latency)
        if random.random() < self._fail_rate:
            raise ProviderError("loadtest injected failure")

    def generate_mother(self, tenant_id: str, prompt: str, storyboard: list[str]) -> dict[str, Any]:
        self._maybe_fail()
        return {"url": f"https://flaky.cdn/{tenant_id}/m.mp4", "duration": 10, "units": 1,
                "meta": {"provider": self.name}}

    def remix(self, tenant_id: str, source_url: str, index: int, changes: dict) -> dict[str, Any]:
        self._maybe_fail()
        return {"url": f"https://flaky.cdn/{tenant_id}/v{index}.mp4", "duration": 8, "units": 1,
                "meta": {"provider": self.name, "index": index}}


_PROVIDERS["loadtest_flaky"] = FlakyProvider
