"""P0：本地视频存储（本地 + CDN 双存）。

火山 CDN 签名 URL 24h 过期；生成成功后把 mp4 下载到 ECS 本地，download_url 优先本地，
CDN 作 fallback。本地副本永不过期，根治「下载/播放失效」。

部署（ECS）：
- STORAGE_DIR=/opt/v4-video-engine/storage/videos
- nginx 把该目录 serve 为静态： STORAGE_BASE_URL=https://video.beautypeaceai.com/static/videos
"""

from __future__ import annotations

import os

import httpx

from config import settings


def local_path(video_id: int) -> str:
    return os.path.join(settings.storage_dir, f"{video_id}.mp4")


def local_url(video_id: int) -> str | None:
    if not settings.storage_base_url:
        return None
    return f"{settings.storage_base_url.rstrip('/')}/{video_id}.mp4"


def download_and_store(video_id: int, cdn_url: str, timeout: float = 60.0) -> dict:
    """下载 CDN mp4 到本地。返回 {cdn_url, local_path, local_url, ok}。失败不抛，回退 CDN。"""
    os.makedirs(settings.storage_dir, exist_ok=True)
    path = local_path(video_id)
    try:
        with httpx.stream("GET", cdn_url, timeout=timeout, follow_redirects=True) as r:
            r.raise_for_status()
            with open(path, "wb") as f:
                for chunk in r.iter_bytes(chunk_size=1 << 16):
                    f.write(chunk)
        ok = os.path.getsize(path) > 0
    except Exception:  # noqa: BLE001  落盘失败回退 CDN
        ok = False
    return {
        "cdn_url": cdn_url,
        "local_path": path if ok else None,
        "local_url": local_url(video_id) if ok else None,
        "ok": ok,
    }


def resolve_download_url(cdn_url: str | None, lurl: str | None) -> str | None:
    """下载地址：本地优先，CDN 兜底。"""
    return lurl or cdn_url
