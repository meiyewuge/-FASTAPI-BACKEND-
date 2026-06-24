"""火山 provider 注册实现（双 Provider）。

VIDEO_PROVIDER 取值：
  volcano_seedance → VolcanoSeedanceProvider（Ark, Bearer，默认）
  volcano_legacy   → VolcanoLegacyProvider（旧 OpenAPI, AK/SK）
"""

from __future__ import annotations

from utils.video_provider import _PROVIDERS, VideoProvider
from utils.volcano_doubao_provider import VolcanoLegacyProvider, VolcanoSeedanceProvider

_PROVIDERS["volcano_seedance"] = VolcanoSeedanceProvider
_PROVIDERS["volcano"] = VolcanoSeedanceProvider          # 别名
_PROVIDERS["volcano_legacy"] = VolcanoLegacyProvider


def build_volcano(name: str = "volcano_seedance") -> VideoProvider:
    cls = _PROVIDERS.get(name, VolcanoSeedanceProvider)
    return cls()
