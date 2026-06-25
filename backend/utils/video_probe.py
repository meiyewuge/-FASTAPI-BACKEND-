"""视频时长探测（V4 P1）。

用 ffprobe 读取视频时长（秒）。失败返回 None（= 时长未知，不计入合格源）。
依赖 ECS 已装 ffmpeg/ffprobe（与 remixer/video_cover 同依赖）。
"""

from __future__ import annotations

import subprocess


def probe_duration(path: str) -> float | None:
    """返回视频时长(秒，float)；失败/无文件返回 None。"""
    if not path:
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nokey=1:noprint_wrappers=1", path],
            capture_output=True, text=True, timeout=30,
        )
        val = (out.stdout or "").strip()
        if not val:
            return None
        return round(float(val), 2)
    except Exception:  # noqa: BLE001  探测失败 = 时长未知
        return None
