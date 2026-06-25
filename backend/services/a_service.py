"""A台业务编排：调用 a_engine 生成母视频 → 落库 → 记账。"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

import cost_engine
from a_engine.generator import generate_mother_video
from config import settings
from models import Video
from utils import video_cover, video_storage


def run(db: Session, tenant_id: str, task_id: str, payload: dict) -> dict:
    prompt = payload["prompt"]
    duration = payload.get("duration", 15)
    resolution = payload.get("resolution", "720p")
    data = generate_mother_video(tenant_id, prompt, duration=duration, resolution=resolution)
    cdn_url = data["url"]
    # V4 P0：参考图（来自上传）随母视频记录，便于追溯（不改火山调用本身）
    if payload.get("image_file_id"):
        data.setdefault("meta", {})["image_file_id"] = payload["image_file_id"]

    video = Video(
        tenant_id=tenant_id,
        store_id=payload.get("store_id"),
        type="mother",
        title=payload.get("title") or data["title"],
        cdn_url=cdn_url,
        download_url=cdn_url,
        share_url=cdn_url,
        volcano_task_id=data["meta"].get("provider_task_id"),
        duration_seconds=float(data.get("duration") or duration),  # V4 P1：单段时长
        meta=json.dumps(data["meta"], ensure_ascii=False),
    )
    db.add(video)
    db.flush()

    # B2：生成成功后落本地（本地优先，CDN 兜底）。dev/mock 默认关闭，ECS 置 STORAGE_ENABLED=true。
    if settings.storage_enabled:
        st = video_storage.download_and_store(video.id, cdn_url, subdir="mother")
        video.local_url = st["local_url"]
        video.download_url = video_storage.resolve_download_url(cdn_url, st["local_url"])
        video.cover_url = video_cover.extract_cover(video.id, st["local_path"] or cdn_url, subdir="mother")

    provider = data["meta"].get("served_by") or data["meta"].get("provider") or ""
    cost_engine.record(
        db,
        tenant_id,
        "video.generate.a",
        data.get("units", 1),
        task_id,
        provider=provider,
        store_id=payload.get("store_id"),
        duration=data.get("duration"),
        resolution=resolution,
    )
    db.commit()

    return {
        "videos": [
            {
                "video_id": video.id,
                "type": "mother",
                "download_url": video.download_url,
                "share_url": video.share_url,
            }
        ]
    }
