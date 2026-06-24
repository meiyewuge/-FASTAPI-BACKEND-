"""火山 provider 注册实现。

把 VolcanoDoubaoProvider 注册进 video_provider 的 provider 注册表，
并提供 build_volcano() 供 get_provider 构建（延迟导入，避免循环依赖）。
"""

from __future__ import annotations

from utils.video_provider import _PROVIDERS, VideoProvider
from utils.volcano_doubao_provider import VolcanoDoubaoProvider

# 注册（cost.provider 记 volcano_seedance；别名 volcano / volcano_doubao 亦可）
for _alias in ("volcano", "volcano_seedance", "volcano_doubao"):
    _PROVIDERS[_alias] = VolcanoDoubaoProvider


def build_volcano() -> VideoProvider:
    return VolcanoDoubaoProvider()
