"""B8：视频封面（首帧提取）。

用 FFmpeg 抽取视频首帧为 jpg，存到本地 storage（与 mp4 同目录），cover_url 走 nginx 静态。
依赖 ECS 已装 ffmpeg（B6 同此依赖）。source 可为本地 mp4 路径或可取 URL。
"""

from __future__ import annotations

import os
import subprocess

from config import settings


def cover_path(video_id: int, subdir: str = "") -> str:
    return os.path.join(settings.storage_dir, subdir, f"{video_id}.jpg")


def cover_url(video_id: int, subdir: str = "") -> str | None:
    if not settings.storage_base_url:
        return None
    base = settings.storage_base_url.rstrip("/")
    seg = f"{subdir}/" if subdir else ""
    return f"{base}/{seg}{video_id}.jpg"


def extract_cover(video_id: int, source: str, subdir: str = "") -> str | None:
    """抽首帧为 jpg，返回 cover_url。失败返回 None，不阻断主流程。"""
    if not source:
        return None
    out = cover_path(video_id, subdir)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", source, "-frames:v", "1", "-q:v", "2", out],
            check=True, capture_output=True, timeout=60,
        )
        ok = os.path.exists(out) and os.path.getsize(out) > 0
    except Exception:  # noqa: BLE001  抽帧失败不影响视频
        ok = False
    return cover_url(video_id, subdir) if ok else None
