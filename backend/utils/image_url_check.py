"""图片公网 HTTPS 校验（V4 P0-B，BUG-3 断裂2 前置）。

提交火山前必须校验每张图片：属于当前 tenant、存在、可生成 HTTPS 公网 URL、本地文件在。
失败统一返回中文错误，避免火山拿不到图导致「词不达意」。

外部可达性（external reachability）在 sandbox 不真发请求；生产可开 reachability 探测。
"""

from __future__ import annotations

import os

from sqlalchemy.orm import Session

from config import settings
from models import Upload

IMAGE_ACCESS_ERROR = "图片无法被视频模型访问，请重新上传或等待处理完成。"


class ImageAccessError(ValueError):
    """图片无法被视频模型访问。"""


def _public_https_url(rec: Upload) -> str | None:
    """生成 HTTPS 公网可访问 URL。upload_base_url 必须是 https。"""
    base = settings.upload_base_url
    if not base or not base.lower().startswith("https://"):
        return None
    # rec.file_url 已按 base 生成；确保 https
    if rec.file_url and rec.file_url.lower().startswith("https://"):
        return rec.file_url
    return None


def resolve_image_roles(db: Session, tenant_id: str, image_file_ids: list[str] | None,
                        roles: list[dict]) -> list[dict]:
    """把 assign_image_roles 的 [{file_id,role}] 补全为 [{file_id,role,url}]，并逐项校验。

    任一图片不属于本租户 / 不存在 / 非图片 / 无 HTTPS 公网 URL / 本地文件缺失 → 抛 ImageAccessError。
    无图片（roles 为空）→ 返回 []（纯文生，合法）。
    """
    if not roles:
        return []
    out = []
    for r in roles:
        fid = r["file_id"]
        rec = (
            db.query(Upload)
            .filter(Upload.file_id == fid, Upload.tenant_id == tenant_id)
            .first()
        )
        if rec is None or rec.file_type != "image":          # 不存在 / 非本租户 / 非图片
            raise ImageAccessError(IMAGE_ACCESS_ERROR)
        if rec.storage_status != "active":                    # 已过期/删除
            raise ImageAccessError(IMAGE_ACCESS_ERROR)
        url = _public_https_url(rec)
        if not url:                                           # 无 HTTPS 公网 URL
            raise ImageAccessError(IMAGE_ACCESS_ERROR)
        if rec.local_path and not os.path.exists(rec.local_path):  # 本地文件缺失
            raise ImageAccessError(IMAGE_ACCESS_ERROR)
        out.append({"file_id": fid, "role": r["role"], "url": url})
    return out
