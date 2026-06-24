"""导出服务：把「筛选」后的视频整理成可下载的导出清单（manifest）。

边界（内容生产冻结）：只产出清单/文件，**不对接任何外部平台、不做分发/发布**。
输入 → 生成 → 筛选 → 导出。导出 = 给运营一份「视频清单 + 下载/分发链接」。
"""

from __future__ import annotations

import csv
import io

from sqlalchemy.orm import Session

from models import Store, Video


def select_videos(
    db: Session,
    tenant_id: str,
    video_ids: list[int] | None = None,
    type: str | None = None,
    strategy: str | None = None,
    store_id: int | None = None,
    source_video_id: int | None = None,
) -> list[Video]:
    """筛选：按 ids 或条件过滤当前租户视频。"""
    q = db.query(Video).filter(Video.tenant_id == tenant_id)
    if video_ids:
        q = q.filter(Video.id.in_(video_ids))
    if type in ("mother", "viral"):
        q = q.filter(Video.type == type)
    if strategy:
        q = q.filter(Video.strategy == strategy)
    if store_id is not None:
        q = q.filter(Video.store_id == store_id)
    if source_video_id is not None:
        q = q.filter(Video.source_video_id == source_video_id)
    return q.order_by(Video.created_at.desc()).all()


def build_manifest(db: Session, tenant_id: str, videos: list[Video]) -> list[dict]:
    names = {s.id: s.name for s in db.query(Store).filter(Store.tenant_id == tenant_id).all()}
    return [
        {
            "video_id": v.id,
            "type": v.type,
            "title": v.title,
            "strategy": v.strategy,
            "store_id": v.store_id,
            "store_name": names.get(v.store_id),
            "download_url": v.download_url,
            "share_url": v.share_url,
        }
        for v in videos
    ]


def manifest_to_csv(items: list[dict]) -> str:
    buf = io.StringIO()
    cols = ["video_id", "type", "title", "strategy", "store_id", "store_name",
            "download_url", "share_url"]
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    for it in items:
        w.writerow({k: it.get(k, "") for k in cols})
    return buf.getvalue()
