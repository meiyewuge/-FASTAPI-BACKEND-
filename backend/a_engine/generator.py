"""A台 · 母视频生成引擎。

链路：一句话需求 → 脚本 → 分镜 → 调用视频 provider → 母视频。
约束：禁止 import b_engine；视频能力经 utils.video_provider。
引擎保持纯净：不碰 DB，返回数据 + 成本，由 service 落库与记账。
"""

from __future__ import annotations

from typing import Any

from utils.video_provider import get_provider


def build_script(prompt: str) -> str:
    """把一句话需求扩写为脚本（占位：真实可接 LLM）。"""
    return f"【脚本】围绕「{prompt}」：开场抓眼球 → 核心卖点 → 行动号召。"


def build_storyboard(script: str) -> list[str]:
    """脚本 → 分镜列表（占位：按句切分）。"""
    parts = [s.strip() for s in script.replace("：", "。").split("。") if s.strip()]
    return parts or [script]


def generate_mother_video(tenant_id: str, prompt: str, duration: int = 15, resolution: str = "720p") -> dict[str, Any]:
    """生成 1 条母视频，返回 {title, url, cover, duration, cost, meta}。

    Args:
        duration: 视频时长（秒），Seedance 2.0 支持 [4, 15]，默认 15
        resolution: 视频分辨率 480p/720p/1080p，默认 720p
    """
    script = build_script(prompt)
    storyboard = build_storyboard(script)
    result = get_provider().generate_mother(tenant_id, prompt, storyboard)
    return {
        "title": prompt[:50],
        "url": result["url"],
        "cover": result.get("cover"),
        "duration": result.get("duration"),
        "units": result.get("units", 1),
        "meta": {"prompt": prompt, "script": script, **result.get("meta", {})},
    }
