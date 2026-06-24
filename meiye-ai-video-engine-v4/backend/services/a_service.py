"""A台业务编排：调用 a_engine 生成母视频 → 落库 → 记账。"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

import cost_engine
from a_engine.generator import generate_mother_video
from config import settings
from models import Video
from utils import video_storage


def run(db: Session, tenant_id: str, task_id: str, payload: dict) -> dict:
    prompt = payload["prompt"]
    data = generate_mother_video(tenant_id, prompt)
    cdn_url = data["url"]

    video = Video(
        tenant_id=tenant_id,
        store_id=payload.get("store_id"),
        type="mother",
        title=payload.get("title") or data["title"],
        cdn_url=cdn_url,
        download_url=cdn_url,
        share_url=cdn_url,
        meta=json.dumps(data["meta"], ensure_ascii=False),
    )
    db.add(video)
    db.flush()

    # P0：生成成功后落本地（本地优先，CDN 兜底）。dev/mock 默认关闭，ECS 置 STORAGE_ENABLED=true。
    if settings.storage_enabled:
        st = video_storage.download_and_store(video.id, cdn_url, subdir="mother")
        video.local_url = st["local_url"]
        video.download_url = video_storage.resolve_download_url(cdn_url, st["local_url"])

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
