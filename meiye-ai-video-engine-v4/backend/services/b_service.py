"""B台业务编排：取母视频 → 调用 b_engine 批量裂变 → 落库 → 记账。"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from b_engine.remixer import remix_videos
from models import Video
from services import cost_service


def run(db: Session, tenant_id: str, task_id: str, payload: dict) -> dict:
    source_id = payload["source_video_id"]
    count = payload.get("count", 10)
    prompt = payload.get("prompt")

    source = (
        db.query(Video)
        .filter(Video.id == source_id, Video.tenant_id == tenant_id, Video.type == "mother")
        .first()
    )
    if source is None:
        raise ValueError(f"母视频不存在或不属于该租户：id={source_id}")

    outputs = remix_videos(tenant_id, source.download_url, count, prompt)

    videos = []
    for o in outputs:
        v = Video(
            tenant_id=tenant_id,
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
        cost_service.record(
            db, tenant_id, "video.remix.b", cost["units"], cost["amount"], task_id
        )
        videos.append(
            {
                "video_id": v.id,
                "type": "viral",
                "download_url": v.download_url,
                "share_url": v.share_url,
            }
        )

    db.commit()
    return {"source_video_id": source.id, "count": len(videos), "videos": videos}
