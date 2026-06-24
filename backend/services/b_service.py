"""B台业务编排：取母视频 → 调用 b_engine 批量裂变 → 落库 → 记账。"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

import cost_engine
from b_engine.remixer import remix_videos
from config import settings
from models import Video
from services import store_service
from utils import video_cover, video_storage


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

    # 门店差异化：取租户门店作为差异化/归因目标（可为空）
    stores = [
        {"id": s.id, "name": s.name, "city": s.city}
        for s in store_service.list_stores(db, tenant_id)
    ]

    # B台视频输入（video-to-video）：母视频 mp4 的可取地址（CDN 公网可取）
    source_url = source.cdn_url or source.download_url
    outputs = remix_videos(tenant_id, source_url, count, prompt, strategy, stores)

    videos = []
    for o in outputs:
        v = Video(
            tenant_id=tenant_id,
            store_id=o.get("store_id"),
            type="viral",
            title=o["title"],
            strategy=o.get("strategy"),
            source_video_id=source.id,
            cdn_url=o["url"],
            download_url=o["url"],
            share_url=o["url"],
            volcano_task_id=o["meta"].get("provider_task_id"),
            meta=json.dumps(o["meta"], ensure_ascii=False),
        )
        db.add(v)
        db.flush()
        if settings.storage_enabled:
            st = video_storage.download_and_store(v.id, o["url"], subdir="viral")
            v.local_url = st["local_url"]
            v.download_url = video_storage.resolve_download_url(o["url"], st["local_url"])
            v.cover_url = video_cover.extract_cover(v.id, st["local_path"] or o["url"], subdir="viral")
        provider = o["meta"].get("served_by") or o["meta"].get("provider") or ""
        cost_engine.record(
            db,
            tenant_id,
            "video.remix.b",
            o.get("units", 1),
            task_id,
            provider=provider,
            store_id=o.get("store_id"),
            duration=o.get("duration"),
        )
        videos.append(
            {
                "video_id": v.id,
                "type": "viral",
                "strategy": o.get("strategy"),
                "store_id": o.get("store_id"),
                "download_url": v.download_url,
                "share_url": v.share_url,
            }
        )

    db.commit()
    return {"source_video_id": source.id, "count": len(videos), "videos": videos}
