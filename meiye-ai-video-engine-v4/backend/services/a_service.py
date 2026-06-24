"""A台业务编排：调用 a_engine 生成母视频 → 落库 → 记账。"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from a_engine.generator import generate_mother_video
from models import Video
from services import cost_service


def run(db: Session, tenant_id: str, task_id: str, payload: dict) -> dict:
    prompt = payload["prompt"]
    data = generate_mother_video(tenant_id, prompt)

    video = Video(
        tenant_id=tenant_id,
        store_id=payload.get("store_id"),
        type="mother",
        title=payload.get("title") or data["title"],
        download_url=data["url"],
        share_url=data["url"],
        meta=json.dumps(data["meta"], ensure_ascii=False),
    )
    db.add(video)
    db.flush()

    cost = data["cost"]
    provider = data["meta"].get("served_by") or data["meta"].get("provider") or ""
    cost_service.record(
        db,
        tenant_id,
        "video.generate.a",
        cost["units"],
        cost["amount"],
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
