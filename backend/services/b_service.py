"""B台业务编排（B9）：取母视频本地文件 → 本地 ffmpeg 裂变 → 归档 viral/ → 落库。

B台 = 纯本地处理，0 成本，不经过火山/provider。母视频本地文件由 A台 B2 落盘产生。
"""

from __future__ import annotations

import json
import os
import tempfile

from sqlalchemy.orm import Session

import cost_engine
from b_engine.remixer import remix_videos
from config import settings
from models import Video
from services import store_service
from utils import video_cover, video_storage


def _mother_local_path(source: Video) -> str:
    """取母视频本地文件路径；不存在则按需从 CDN 下载到临时文件（B台需要本地文件）。"""
    path = video_storage.local_path(source.id, "mother")
    if os.path.exists(path):
        return path
    cdn = source.cdn_url or source.download_url
    if cdn and cdn.startswith("http"):
        tmp = os.path.join(tempfile.mkdtemp(), f"mother_{source.id}.mp4")
        video_storage.download_to(cdn, tmp)
        return tmp
    raise ValueError(f"母视频本地文件缺失且无可下载 CDN：id={source.id}")


def run(db: Session, tenant_id: str, task_id: str, payload: dict) -> dict:
    source_id = payload["source_video_id"]
    count = payload.get("count", 10)
    prompt = payload.get("prompt")
    strategy = payload.get("strategy", "mix")

    source = (
        db.query(Video)
        .filter(Video.id == source_id, Video.tenant_id == tenant_id, Video.type == "mother")
        .first()
    )
    if source is None:
        raise ValueError(f"母视频不存在或不属于该租户：id={source_id}")

    stores = [
        {"id": s.id, "name": s.name, "city": s.city}
        for s in store_service.list_stores(db, tenant_id)
    ]

    # B9：取母视频本地文件路径，本地 ffmpeg 裂变（非 URL、不走 provider）
    source_path = _mother_local_path(source)
    outputs = remix_videos(tenant_id, source_path, count, prompt, strategy, stores)

    viral_dir = os.path.join(settings.storage_dir, "viral")
    os.makedirs(viral_dir, exist_ok=True)

    videos = []
    for o in outputs:
        v = Video(
            tenant_id=tenant_id,
            store_id=o.get("store_id"),
            type="viral",
            title=o["title"],
            strategy=o.get("strategy"),
            source_video_id=source.id,
            meta=json.dumps(o["meta"], ensure_ascii=False),
        )
        db.add(v)
        db.flush()

        # 归档本地成片为 viral/{id}.mp4 + 本地URL + 封面
        final_path = os.path.join(viral_dir, f"{v.id}.mp4")
        os.replace(o["local_path"], final_path)
        v.local_url = video_storage.local_url(v.id, "viral")
        v.download_url = v.local_url
        v.share_url = v.local_url
        v.cover_url = video_cover.extract_cover(v.id, final_path, "viral")

        # B台本地裂变 = 0 元
        cost_engine.record(
            db, tenant_id, "video.remix.b", o.get("units", 0), task_id,
            provider="local_ffmpeg", store_id=o.get("store_id"),
            duration=o.get("duration"), amount=0.0,
        )
        videos.append({
            "video_id": v.id,
            "type": "viral",
            "strategy": o.get("strategy"),
            "store_id": o.get("store_id"),
            "download_url": v.download_url,
            "cover_url": v.cover_url,
        })

    db.commit()
    return {"source_video_id": source.id, "count": len(videos), "videos": videos}
