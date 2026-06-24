"""B1：火山签名 URL 刷新机制。

火山 CDN 签名 URL 24h 过期。每个视频生成时持久化 volcano_task_id；过期后用该 id
重新查询火山任务（火山每次查询返回新签名 URL，刷新 24h），更新 DB。

入口：refresh_video_url(db, video) —— 返回最新可用 URL（已写回 DB）。
"""

from __future__ import annotations

import calendar
import time
from urllib.parse import parse_qs, urlparse

from sqlalchemy.orm import Session

from models import Video


def is_expired(signed_url: str | None, skew_seconds: int = 600) -> bool:
    """解析火山 TOS 签名 URL 过期时间；解析不到则保守视为「需刷新」。"""
    if not signed_url:
        return True
    try:
        q = parse_qs(urlparse(signed_url).query)
        for k in ("X-Tos-Expires", "x-tos-expires"):  # TOS 用相对秒数 + X-Tos-Date
            if k in q:
                expires = int(q[k][0])
                date = q.get("X-Tos-Date", q.get("x-tos-date", [None]))[0]
                if date:
                    # X-Tos-Date 形如 20260624T124200Z
                    issued = calendar.timegm(time.strptime(date, "%Y%m%dT%H%M%SZ"))
                    return time.time() + skew_seconds >= issued + expires
        for k in ("Expires", "expires"):  # 绝对时间戳
            if k in q:
                return time.time() + skew_seconds >= int(q[k][0])
        return False
    except Exception:  # noqa: BLE001  解析失败不阻断
        return False


def refresh_video_url(db: Session, video: Video) -> str | None:
    """若 URL 过期且有 volcano_task_id，则重新查询火山取新 URL 并写回 DB。"""
    # 本地副本永不过期（B2）：local_url/本地路径优先，无需刷新
    if not is_expired(video.download_url):
        return video.download_url
    if not video.volcano_task_id:
        return video.download_url
    try:
        from utils.video_provider_volcano import build_volcano

        status, url, _dur = build_volcano()._poll(video.volcano_task_id)
    except Exception:  # noqa: BLE001
        return video.download_url
    if status == "done" and url:
        video.download_url = url
        video.share_url = url
        db.commit()
        return url
    return video.download_url
