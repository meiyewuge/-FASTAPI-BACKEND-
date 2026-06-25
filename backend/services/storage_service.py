"""存储与自动清理（V4 P0）。

- 删除视频：删服务器文件，保留 DB 记录（storage_status=deleted），便于页面显示「已删除/已过期」。
- 磁盘/数量统计：disk 全局，数量按 tenant 隔离。
- 清理：扫描 expires_at < now 的视频/上传，删文件并置 expired（不删 DB 记录）。
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime

from sqlalchemy.orm import Session

from config import settings
from models import Upload, Video
from utils import video_cover, video_storage


def _remove_video_files(v: Video) -> None:
    subdir = "viral" if v.type == "viral" else "mother"
    for p in (video_storage.local_path(v.id, subdir), video_cover.cover_path(v.id, subdir)):
        try:
            if p and os.path.exists(p):
                os.remove(p)
        except OSError:
            pass


def delete_video(db: Session, tenant_id: str, video_id: int, is_super: bool = False) -> str:
    """删除服务器文件并标记 deleted（DB 记录保留）。

    返回 "deleted" | "not_found" | "forbidden"。
    - 普通 user / invite_admin：只能删本租户视频；跨租户 → forbidden。
    - super_admin：可删任意租户视频。
    """
    v = db.query(Video).filter(Video.id == video_id).first()
    if v is None:
        return "not_found"
    if not is_super and v.tenant_id != tenant_id:
        return "forbidden"
    _remove_video_files(v)
    v.storage_status = "deleted"
    db.commit()
    return "deleted"


def _tenant_counts(db: Session, tenant_id: str) -> dict:
    def _count(vtype: str) -> int:
        return (
            db.query(Video)
            .filter(Video.tenant_id == tenant_id, Video.type == vtype,
                    Video.storage_status == "active")
            .count()
        )
    upload_count = (
        db.query(Upload)
        .filter(Upload.tenant_id == tenant_id, Upload.storage_status == "active")
        .count()
    )
    return {"mother_count": _count("mother"), "viral_count": _count("viral"),
            "upload_count": upload_count}


def _tenant_used_mb(db: Session, tenant_id: str) -> float:
    """本租户占用估算：上传文件大小 + 活跃视频文件实际大小（best-effort）。"""
    total = 0
    for u in (db.query(Upload)
              .filter(Upload.tenant_id == tenant_id, Upload.storage_status == "active").all()):
        total += int(u.file_size or 0)
    for v in (db.query(Video)
              .filter(Video.tenant_id == tenant_id, Video.storage_status == "active").all()):
        subdir = "viral" if v.type == "viral" else "mother"
        p = video_storage.local_path(v.id, subdir)
        try:
            if os.path.exists(p):
                total += os.path.getsize(p)
        except OSError:
            pass
    return round(total / (1024 * 1024), 2)


def storage_status(db: Session, tenant_id: str, role: str = "user") -> dict:
    """角色感知的存储状态：
    - user / invite_admin：scope=tenant，仅本租户数量与占用估算（不暴露全局磁盘）。
    - super_admin：scope=global，ECS 磁盘 + 全局总量 + 各租户概览。
    """
    if role != "super_admin":
        counts = _tenant_counts(db, tenant_id)
        return {
            "scope": "tenant",
            "tenant_id": tenant_id,
            "mother_count": counts["mother_count"],
            "viral_count": counts["viral_count"],
            "upload_count": counts["upload_count"],
            "estimated_used_mb": _tenant_used_mb(db, tenant_id),
        }

    # super_admin：全局视图
    os.makedirs(settings.storage_dir, exist_ok=True)
    du = shutil.disk_usage(settings.storage_dir)
    gb = 1024 ** 3

    def _gcount(vtype: str) -> int:
        return db.query(Video).filter(Video.type == vtype, Video.storage_status == "active").count()

    upload_total = db.query(Upload).filter(Upload.storage_status == "active").count()

    # 各租户概览
    tenant_ids = [r[0] for r in db.query(Video.tenant_id).distinct().all()]
    tenant_summary = []
    for tid in tenant_ids:
        c = _tenant_counts(db, tid)
        tenant_summary.append({"tenant_id": tid, **c})

    return {
        "scope": "global",
        "disk_total_gb": round(du.total / gb, 2),
        "disk_used_gb": round(du.used / gb, 2),
        "disk_used_percent": round(du.used / du.total * 100, 1) if du.total else 0.0,
        "mother_count": _gcount("mother"),
        "viral_count": _gcount("viral"),
        "upload_count": upload_total,
        "tenant_summary": tenant_summary,
    }


def run_cleanup(db: Session, now: datetime | None = None) -> dict:
    """清理到期文件：删服务器文件，storage_status→expired，保留 DB 记录。"""
    now = now or datetime.utcnow()
    vids = (
        db.query(Video)
        .filter(Video.expires_at.isnot(None), Video.expires_at < now,
                Video.storage_status == "active")
        .all()
    )
    for v in vids:
        _remove_video_files(v)
        v.storage_status = "expired"

    ups = (
        db.query(Upload)
        .filter(Upload.expires_at.isnot(None), Upload.expires_at < now,
                Upload.storage_status == "active")
        .all()
    )
    for u in ups:
        try:
            if u.local_path and os.path.exists(u.local_path):
                os.remove(u.local_path)
        except OSError:
            pass
        u.storage_status = "expired"

    db.commit()
    return {"videos_expired": len(vids), "uploads_expired": len(ups)}
