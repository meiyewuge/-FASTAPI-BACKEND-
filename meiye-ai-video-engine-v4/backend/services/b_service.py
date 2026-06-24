"""B台业务编排：取母视频 → 调用 b_engine 批量裂变 → 落库 → 记账。"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from b_engine.remixer import remix_videos
from models import Video
from services import cost_service, store_service


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

    outputs = remix_videos(tenant_id, source.download_url, count, prompt, strategy, stores)

    videos = []
    for o in outputs:
        v = Video(
            tenant_id=tenant_id,
            store_id=o.get("store_id"),
            type="viral",
            title=o["title"],
            source_video_id=source.id,
            download_url=o["url"],
            share_url=o["url"],
            meta=json.dumps(o["meta"], ensure_ascii=False),
        )
        db.add(v)
        db.flush()
        cost = o["cost"]
        provider = o["meta"].get("served_by") or o["meta"].get("provider") or ""
        cost_service.record(
            db,
            tenant_id,
            "video.remix.b",
            cost["units"],
            cost["amount"],
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
