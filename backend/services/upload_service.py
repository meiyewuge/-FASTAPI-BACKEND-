"""上传业务（Patch2）：校验 → 落盘 → 入库 → 返回 file 信息。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from models import Upload
from utils import upload_util


def handle_upload(db: Session, tenant_id: str, ftype: str, filename: str | None, data: bytes) -> dict:
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
    )
    db.add(rec)
    db.commit()
    return {
        "file_id": saved["file_id"],
        "file_url": saved["file_url"],
        "file_type": ftype,
        "file_size": saved["size"],
        "local_path": saved["local_path"],
    }
