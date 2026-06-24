"""B台 · 混剪裂变引擎。

链路：母视频 → 切片 → 重组 → 改字幕/开头/结尾 → 输出 count 条裂变视频。
约束：禁止 import a_engine；视频能力经 utils.video_provider。
引擎保持纯净：不碰 DB，返回数据 + 成本列表，由 service 落库与记账。
"""

from __future__ import annotations

from typing import Any

from utils.video_provider import get_provider

_HOOKS = ["疑问开头", "数字开头", "痛点开头", "福利开头", "对比开头"]
_ENDINGS = ["到店领取", "私信咨询", "限时活动", "扫码预约", "关注解锁"]


def _plan_changes(index: int, prompt: str | None) -> dict:
    """为第 index 条裂变视频生成差异化方案（去重思路：开头/结尾/字幕轮换）。"""
    return {
        "hook": _HOOKS[index % len(_HOOKS)],
        "ending": _ENDINGS[index % len(_ENDINGS)],
        "subtitle": f"版本{index + 1}" + (f"·{prompt}" if prompt else ""),
    }


def remix_videos(
    tenant_id: str, source_url: str, count: int, prompt: str | None = None
) -> list[dict[str, Any]]:
    """基于母视频批量产出 count 条裂变视频。"""
    provider = get_provider()
    outputs: list[dict[str, Any]] = []
    for i in range(count):
        changes = _plan_changes(i, prompt)
        r = provider.remix(tenant_id, source_url, i, changes)
        outputs.append(
            {
                "title": changes["subtitle"],
                "url": r["url"],
                "cost": r["cost"],
                "meta": {"changes": changes, **r.get("meta", {})},
            }
        )
    return outputs
