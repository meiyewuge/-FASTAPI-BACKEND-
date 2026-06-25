"""上传业务（Patch2 + V4 P0 批量）。

单文件：校验 → 落盘 → 入库 → 返回。
批量：混合 image/video/file(doc/docx/zip)/text，逐个处理，返回 {uploaded, failed}。
上传 video 额外登记为 source_type=uploaded 的母/源视频，进入「母视频/源视频陈列面」。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from config import settings
from models import Upload, Video
from utils import upload_util, video_cover, video_storage


def _upload_expiry() -> datetime | None:
    days = settings.upload_retention_days
    return datetime.utcnow() + timedelta(days=days) if days and days > 0 else None


def _save_record(db: Session, tenant_id: str, ftype: str, filename: str | None, data: bytes) -> Upload:
    ext = upload_util.validate(ftype, filename, data)
    saved = upload_util.save(ftype, ext, data)
    rec = Upload(
        file_id=saved["file_id"],
        tenant_id=tenant_id,
        file_type=ftype,
        file_name=upload_util.safe_name(filename) if filename else f"{saved['file_id']}.{ext}",
        file_size=saved["size"],
        local_path=saved["local_path"],
        file_url=saved["file_url"],
        storage_status="active",
        expires_at=_upload_expiry(),
    )
    db.add(rec)
    db.flush()
    return rec


def register_uploaded_video(db: Session, tenant_id: str, upload_rec: Upload, data: bytes) -> Video:
    """把上传的视频登记为 source_type=uploaded 的母/源视频，落 storage/mother 供 B台裂变。"""
    v = Video(
        tenant_id=tenant_id,
        type="mother",
        source_type="uploaded",
        storage_status="active",
        title=upload_rec.file_name,
        origin_file_id=upload_rec.file_id,
        expires_at=upload_rec.expires_at,
        meta=json.dumps({"from_upload": upload_rec.file_id}, ensure_ascii=False),
    )
    db.add(v)
    db.flush()
    # 落 storage/mother/{vid}.mp4（B台 _mother_local_path 即取此路径）
    mother_dir = os.path.join(settings.storage_dir, "mother")
    os.makedirs(mother_dir, exist_ok=True)
    final_path = os.path.join(mother_dir, f"{v.id}.mp4")
    with open(final_path, "wb") as f:
        f.write(data)
    v.local_url = video_storage.local_url(v.id, "mother")
    v.download_url = v.local_url or upload_rec.file_url
    v.share_url = v.download_url
    v.cover_url = video_cover.extract_cover(v.id, final_path, "mother")
    v.thumbnail_path = video_cover.cover_path(v.id, "mother") if v.cover_url else None
    db.flush()
    return v


def handle_upload(db: Session, tenant_id: str, ftype: str, filename: str | None, data: bytes) -> dict:
    """单文件上传（Patch2 接口）。video 也登记进母视频陈列面。"""
    rec = _save_record(db, tenant_id, ftype, filename, data)
    video_id = None
    if ftype == "video":
        v = register_uploaded_video(db, tenant_id, rec, data)
        video_id = v.id
    db.commit()
    return {
        "file_id": rec.file_id,
        "file_url": rec.file_url,
        "file_type": ftype,
        "file_size": rec.file_size,
        "local_path": rec.local_path,
        "video_id": video_id,
    }


def _item(rec: Upload, video_id: int | None = None, extra: dict | None = None) -> dict:
    out = {
        "file_id": rec.file_id,
        "file_name": rec.file_name,
        "file_type": rec.file_type,
        "file_size": rec.file_size,
        "file_url": rec.file_url,
        "thumbnail_url": None,
        "status": rec.storage_status,
        "video_id": video_id,
    }
    if extra:
        out.update(extra)
    return out


def handle_batch(db: Session, tenant_id: str, files: list[tuple[str | None, bytes]],
                 texts: list[str] | None = None) -> dict:
    """批量上传：混合 image/video/file(doc/docx/zip)；text 单独入参。

    返回 {"uploaded": [...], "failed": [{file_name, reason}]}。
    """
    uploaded: list[dict] = []
    failed: list[dict] = []

    # 单批总量上限（防撑爆 ECS）
    total_bytes = sum(len(d) for _, d in files)
    if total_bytes > settings.max_batch_total_gb * 1024 * 1024 * 1024:
        return {"uploaded": [], "failed": [{"file_name": "*", "reason": "单批总量超过上限"}]}

    counts = {"image": 0, "video": 0, "file": 0}
    for filename, data in files:
        cat = upload_util.category_of(filename)
        if cat is None:
            failed.append({"file_name": filename, "reason": "不支持的文件类型"})
            continue
        counts[cat] += 1
        if counts[cat] > settings.max_batch_count:
            failed.append({"file_name": filename, "reason": f"{cat} 单批数量超过 {settings.max_batch_count}"})
            continue
        try:
            extra = None
            # zip：P0 仅存储 + 列出条目（防 zip bomb），不深度解压
            if upload_util._ext_of(filename) == "zip":
                info = upload_util.inspect_zip(data)
                extra = {"zip_entries": info["entries"], "zip_total_uncompressed": info["total_uncompressed"]}
            rec = _save_record(db, tenant_id, cat, filename, data)
            video_id = None
            if cat == "video":
                v = register_uploaded_video(db, tenant_id, rec, data)
                video_id = v.id
                extra = {**(extra or {}), "thumbnail_url": v.cover_url}
            uploaded.append(_item(rec, video_id, extra))
        except upload_util.UploadError as e:
            failed.append({"file_name": filename, "reason": str(e)})

    for txt in (texts or []):
        try:
            rec = _save_record(db, tenant_id, "text", "text.txt", (txt or "").encode("utf-8"))
            uploaded.append(_item(rec))
        except upload_util.UploadError as e:
            failed.append({"file_name": "text", "reason": str(e)})

    db.commit()
    return {"uploaded": uploaded, "failed": failed}
