"""上传校验与落盘（Patch2）。

安全：文件名去危险字符；落盘用 uuid 文件名（杜绝路径穿越）；校验扩展名 + MIME 魔数 + 大小。
"""

from __future__ import annotations

import os
import re
import uuid
import zipfile

from config import settings

SUBDIR = {"image": "images", "text": "texts", "video": "videos", "file": "files"}
_EXT = {
    "image": {"jpg", "jpeg", "png", "webp"},
    "video": {"mp4", "mov", "avi"},
    "file": {"doc", "docx", "zip"},
    "text": {"txt", "md", ""},
}

# 扩展名 → 类别（批量上传混合文件分流用）
_EXT2TYPE = {e: t for t, exts in _EXT.items() for e in exts if e}


class UploadError(ValueError):
    pass


def category_of(filename: str | None) -> str | None:
    """按扩展名推断上传类别 image|video|file；未知返回 None。"""
    return _EXT2TYPE.get(_ext_of(filename))


def safe_name(name: str | None) -> str:
    """去危险字符（仅保留中英文/数字/.-_），并去掉路径成分。"""
    base = os.path.basename(name or "").replace("\\", "/").split("/")[-1]
    cleaned = re.sub(r"[^\w.\-一-龥]", "_", base)
    return cleaned[:120] or "file"


def _ext_of(name: str | None) -> str:
    return (os.path.splitext(name or "")[1].lower().lstrip(".")) if name else ""


def _max_bytes(ftype: str) -> int:
    if ftype == "image":
        return settings.max_image_mb * 1024 * 1024
    if ftype == "video":
        return settings.max_video_mb * 1024 * 1024
    if ftype == "file":
        return settings.max_doc_mb * 1024 * 1024
    return 5 * 1024 * 1024  # text


def _magic_ok(ftype: str, ext: str, data: bytes) -> bool:
    if ftype == "text":
        return True
    head = data[:16]
    if ftype == "image":
        if ext in ("jpg", "jpeg"):
            return head[:3] == b"\xff\xd8\xff"
        if ext == "png":
            return head[:8] == b"\x89PNG\r\n\x1a\n"
        if ext == "webp":
            return head[:4] == b"RIFF" and data[8:12] == b"WEBP"
    if ftype == "video":
        if ext in ("mp4", "mov"):
            return data[4:8] == b"ftyp"
        if ext == "avi":
            return head[:4] == b"RIFF" and data[8:12] == b"AVI "
    if ftype == "file":
        # docx/zip 同为 ZIP 容器（PK\x03\x04）；doc 为 OLE 复合文档
        if ext in ("zip", "docx"):
            return head[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
        if ext == "doc":
            return head[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    return False


def inspect_zip(data: bytes) -> dict:
    """安全列出 zip 内容（不解压），防 zip bomb：限制条目数/解压总大小/绝对或穿越路径。

    返回 {"entries": [names...], "total_uncompressed": int}；越限抛 UploadError。
    """
    import io

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise UploadError("非法或损坏的 zip")
    infos = zf.infolist()
    if len(infos) > settings.zip_max_entries:
        raise UploadError(f"zip 条目过多（>{settings.zip_max_entries}），疑似 zip bomb")
    total = 0
    names = []
    for zi in infos:
        name = zi.filename
        # 防穿越：禁止绝对路径与 .. 成分
        if name.startswith("/") or name.startswith("\\") or ".." in name.replace("\\", "/").split("/"):
            raise UploadError(f"zip 含非法路径：{name}")
        total += zi.file_size
        if total > settings.zip_max_total_mb * 1024 * 1024:
            raise UploadError(f"zip 解压总大小超限（>{settings.zip_max_total_mb}MB），疑似 zip bomb")
        names.append(name)
    return {"entries": names, "total_uncompressed": total}


def validate(ftype: str, filename: str | None, data: bytes) -> str:
    """校验类型/扩展名/大小/魔数，返回规范化扩展名。失败抛 UploadError。"""
    if ftype not in SUBDIR:
        raise UploadError(f"不支持的 type：{ftype}")
    ext = _ext_of(filename) or ("txt" if ftype == "text" else "")
    if ext not in _EXT[ftype]:
        raise UploadError(f"{ftype} 不支持扩展名 .{ext}")
    if len(data) == 0:
        raise UploadError("空文件")
    if len(data) > _max_bytes(ftype):
        raise UploadError(f"{ftype} 超过大小上限")
    if not _magic_ok(ftype, ext, data):
        raise UploadError("文件内容与扩展名/类型不符（MIME 校验失败）")
    return ext or "txt"


def save(ftype: str, ext: str, data: bytes) -> dict:
    """落盘到 uploads/{subdir}/{uuid}.{ext}（uuid 文件名，无穿越风险）。"""
    subdir = SUBDIR[ftype]
    target_dir = os.path.join(settings.upload_dir, subdir)
    os.makedirs(target_dir, exist_ok=True)
    file_id = uuid.uuid4().hex
    fname = f"{file_id}.{ext}"
    path = os.path.join(target_dir, fname)
    with open(path, "wb") as f:
        f.write(data)
    file_url = None
    if settings.upload_base_url:
        file_url = f"{settings.upload_base_url.rstrip('/')}/{subdir}/{fname}"
    return {"file_id": file_id, "local_path": path, "file_url": file_url, "size": len(data)}
