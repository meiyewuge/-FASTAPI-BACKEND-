"""存量视频 duration_seconds 回填脚本（V4 P1）。

部署时运行：cd backend && python -m tasks.backfill_duration
用 ffprobe 扫描 storage 下的本地视频文件，回填 videos.duration_seconds。
- 仅处理 storage_status='active' 且 duration_seconds 为 NULL 的视频。
- 找不到本地文件 / ffprobe 失败 → 保持 NULL（= 时长未知，不计入合格源）。
- 只读本地文件，不调用火山，不做大文件压测。
"""

from __future__ import annotations

import os

from db import SessionLocal
from models import Video
from utils import video_probe, video_storage

# 不同类型视频的本地子目录（A台 compose 落在 composed）
_SUBDIRS = {
    "viral": ["viral"],
    "mother": ["mother", "composed"],
}


def _find_local(v: Video) -> str | None:
    for subdir in _SUBDIRS.get(v.type, ["mother", "viral", "composed"]):
        p = video_storage.local_path(v.id, subdir)
        if p and os.path.exists(p):
            return p
    return None


def run() -> dict:
    db = SessionLocal()
    updated = failed = 0
    try:
        rows = (
            db.query(Video)
            .filter(Video.storage_status == "active", Video.duration_seconds.is_(None))
            .all()
        )
        for v in rows:
            path = _find_local(v)
            dur = video_probe.probe_duration(path) if path else None
            if dur is not None:
                v.duration_seconds = dur
                updated += 1
            else:
                failed += 1   # 保持 NULL（时长未知）
        db.commit()
    finally:
        db.close()
    return {"scanned": updated + failed, "updated": updated, "unknown": failed}


if __name__ == "__main__":
    r = run()
    print(f"[backfill_duration] scanned={r['scanned']} updated={r['updated']} unknown(NULL)={r['unknown']}")
