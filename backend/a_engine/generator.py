"""A台 · 母视频生成引擎。

链路：一句话需求 → 脚本 → 分镜 → 调用视频 provider → 母视频。
约束：禁止 import b_engine；视频能力经 utils.video_provider。
引擎保持纯净：不碰 DB，返回数据 + 成本，由 service 落库与记账。
"""

from __future__ import annotations

from typing import Any

from utils.script_writer import build_script as _build_script
from utils.video_provider import get_provider


def build_script(prompt: str) -> str:
    """把一句话需求扩写为分镜脚本（B5：可插拔 rule/llm，见 utils.script_writer）。"""
    return _build_script(prompt)


def build_storyboard(script: str) -> list[str]:
    """脚本 → 分镜列表（占位：按句切分）。"""
    parts = [s.strip() for s in script.replace("：", "。").split("。") if s.strip()]
    return parts or [script]


def generate_mother_video(tenant_id: str, prompt: str, duration: int = 15, resolution: str = "720p",
                          content: list | None = None, generate_audio: bool | None = None,
                          ratio: str | None = None) -> dict[str, Any]:
    """生成 1 条母视频，返回 {title, url, cover, duration, cost, meta}。

    V4 P0-B：content[] 非空时走多模态（导演引擎 text + image_url role）；否则纯文生兼容。
    """
    script = build_script(prompt)
    storyboard = build_storyboard(script)
    # B4：duration/resolution 透传；P0-B：content[]/generate_audio/ratio 透传到 provider
    result = get_provider().generate_mother(
        tenant_id, prompt, storyboard, duration=duration, resolution=resolution,
        content=content, generate_audio=generate_audio, ratio=ratio,
    )
    return {
        "title": prompt[:50],
        "url": result["url"],
        "cover": result.get("cover"),
        "duration": result.get("duration"),
        "units": result.get("units", 1),
        "meta": {"prompt": prompt, "script": script, **result.get("meta", {})},
    }
