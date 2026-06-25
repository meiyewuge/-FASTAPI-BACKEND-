"""V4 页面重构 P0 验证：批量上传 / 上传视频进陈列面 / 批量裂变 / 存储与清理 / 租户隔离。

覆盖（对应吴哥要求）：
- 批量上传 3 个小视频成功；上传视频进入 mother/source 列表
- 批量上传图片 3 张成功
- 上传 docx 成功；非法文件拒绝
- 批量裂变 2 个源视频各 1 条成功；B台批量裂变成本为 0；结果进入 viral 列表
- expires_at 正确写入
- 删除视频接口可删服务器文件；storage/status 正常
- 普通租户只能看自己的文件
- Patch6 权限体系不受影响（登录签发带 role 的 JWT、/api/me 正常）

跑法：cd backend && python tests/verify_v4_p0.py
"""
import io
import os
import subprocess
import sys
import tempfile
import zipfile

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
os.environ["DATABASE_URL"] = "sqlite:///./_v4p0_test.db"

import config
import db as _db

_STORAGE = os.path.join(tempfile.mkdtemp(), "videos")
_UPLOAD = os.path.join(tempfile.mkdtemp(), "uploads")

# 最小合法 PNG（1x1）
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360000002000100ffff03000006000557bfabd4"
    "0000000049454e44ae426082"
)


def _mp4_bytes() -> bytes:
    d = tempfile.mkdtemp()
    p = os.path.join(d, "v.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=320x240:d=1",
         "-pix_fmt", "yuv420p", p],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    with open(p, "rb") as f:
        return f.read()


def _docx_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<x/>")
        z.writestr("word/document.xml", "<w/>")
    return buf.getvalue()


def _zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.txt", "hello")
        z.writestr("b.txt", "world")
    return buf.getvalue()


def _client():
    _db.engine.dispose()
    if os.path.exists("./_v4p0_test.db"):
        os.remove("./_v4p0_test.db")
    config.settings.auth_required = True
    config.settings.jwt_secret = "s"
    config.settings.admin_key = "K"
    config.settings.storage_dir = _STORAGE
    config.settings.storage_base_url = "https://test.local/static/videos"
    config.settings.upload_dir = _UPLOAD
    config.settings.upload_base_url = "https://test.local/static/uploads"
    config.settings.viral_retention_days = 5
    config.settings.upload_retention_days = 7
    from fastapi.testclient import TestClient
    from main import app
    _db.init_db()
    return TestClient(app)


def _hdr(tenant):
    from utils import jwt_util
    return {"Authorization": f"Bearer {jwt_util.encode({'tenant_id': tenant, 'phone': tenant}, 's')}"}


def main():
    c = _client()
    A = _hdr("tenantA")
    B = _hdr("tenantB")

    # 1) 批量上传 3 个小视频 → uploaded 3，进入 mother 列表（source_type=uploaded）
    vids = _mp4_bytes()
    files = [("files", (f"clip{i}.mp4", vids, "video/mp4")) for i in range(3)]
    r = c.post("/api/uploads/batch", files=files, headers=A).json()["data"]
    assert len(r["uploaded"]) == 3 and not r["failed"], r
    vid_ids = [u["video_id"] for u in r["uploaded"]]
    assert all(vid_ids), r
    ml = c.get("/api/videos", params={"type": "mother", "source_type": "uploaded"}, headers=A).json()["data"]
    assert ml["total"] == 3, ml
    print("  ✔ 批量上传 3 视频成功 → 进入母/源视频陈列面（source_type=uploaded）")

    # 2) 批量上传 3 张图片成功
    imgs = [("files", (f"p{i}.png", _PNG, "image/png")) for i in range(3)]
    r = c.post("/api/uploads/batch", files=imgs, headers=A).json()["data"]
    assert len(r["uploaded"]) == 3 and not r["failed"], r
    print("  ✔ 批量上传 3 图片成功")

    # 3) 上传 docx + zip 成功；非法文件拒绝
    r = c.post("/api/uploads/batch",
               files=[("files", ("doc.docx", _docx_bytes(), "application/octet-stream")),
                      ("files", ("pack.zip", _zip_bytes(), "application/zip")),
                      ("files", ("bad.exe", b"MZxx", "application/octet-stream")),
                      ("files", ("fake.mp4", _PNG, "video/mp4"))],
               headers=A).json()["data"]
    ok_names = {u["file_name"] for u in r["uploaded"]}
    fail_names = {f["file_name"] for f in r["failed"]}
    assert "doc.docx" in ok_names and "pack.zip" in ok_names, r
    assert "bad.exe" in fail_names and "fake.mp4" in fail_names, r
    zip_item = next(u for u in r["uploaded"] if u["file_name"] == "pack.zip")
    assert zip_item.get("zip_entries") == ["a.txt", "b.txt"], zip_item
    print("  ✔ docx/zip 上传成功（zip 列出条目）；非法文件(exe/魔数不符)被拒")

    # 4) 批量裂变（P1：3 个合格源，duration≥30；auto_ratio=1 保持测试轻量）
    from models import Video as _V
    s = _db.SessionLocal()
    for i in vid_ids:
        s.get(_V, i).duration_seconds = 35.0
    s.commit(); s.close()
    r = c.post("/api/b/batch-generate",
               json={"prompt": "抗衰主题", "source_video_ids": vid_ids, "auto_ratio": 1},
               headers=A).json()["data"]
    batch_id = r["batch_id"]
    assert r["total_outputs"] == 3 and r["source_count"] == 3, r
    st = c.get(f"/api/b/batch/{batch_id}", headers=A).json()["data"]
    assert st["status"] == "done" and st["completed"] == 3 and st["failed"] == 0, st
    print(f"  ✔ 批量裂变 3 合格源（auto_ratio=1）→ batch done, completed=3")

    # 5) 结果进入 viral 列表
    vl = c.get("/api/videos", params={"type": "viral", "batch_id": batch_id}, headers=A).json()["data"]
    assert vl["total"] == 3, vl
    assert all(it["source_type"] == "remixed" for it in vl["items"]), vl
    print("  ✔ 裂变结果进入裂变视频陈列面（source_type=remixed）")

    # 6) B台批量裂变成本为 0
    from models import CostRecord
    s = _db.SessionLocal()
    remix_amt = sum(
        x.amount or 0 for x in s.query(CostRecord)
        .filter(CostRecord.tenant_id == "tenantA", CostRecord.api_name == "video.remix.b").all()
    )
    s.close()
    assert remix_amt == 0, remix_amt
    print("  ✔ B台批量裂变成本 = 0（local_ffmpeg）")

    # 7) expires_at 正确写入（viral 5 天、uploaded 7 天）
    assert all(it["expires_at"] for it in vl["items"]), "viral 应有 expires_at"
    assert all(it["expires_at"] for it in ml["items"]), "uploaded 应有 expires_at"
    print("  ✔ expires_at 已写入（viral / uploaded 均临时保留）")

    # 8) 删除视频 → 服务器文件删除 + storage_status=deleted
    target = vl["items"][0]["video_id"]
    fpath = os.path.join(_STORAGE, "viral", f"{target}.mp4")
    assert os.path.exists(fpath), fpath
    assert c.delete(f"/api/videos/{target}", headers=A).json()["code"] == 0
    assert not os.path.exists(fpath), "文件应已删除"
    after = c.get("/api/videos", params={"type": "viral", "batch_id": batch_id, "include_expired": True}, headers=A).json()["data"]
    assert any(it["video_id"] == target and it["storage_status"] == "deleted" for it in after["items"]), after
    # 默认列表（不含 expired/deleted）应少 1（3→2）
    vis = c.get("/api/videos", params={"type": "viral", "batch_id": batch_id}, headers=A).json()["data"]
    assert vis["total"] == 2, vis
    print("  ✔ 删除视频删服务器文件并标记 deleted（DB 记录保留）")

    # 9) storage/status 正常（普通 user → scope=tenant，不暴露全局磁盘）
    ss = c.get("/api/storage/status", headers=A).json()["data"]
    assert ss["scope"] == "tenant", ss
    assert "disk_total_gb" not in ss, ss
    for k in ("mother_count", "viral_count", "upload_count", "estimated_used_mb"):
        assert k in ss, ss
    assert ss["mother_count"] == 3, ss
    print(f"  ✔ /api/storage/status（user→tenant scope）：mother={ss['mother_count']} viral={ss['viral_count']} upload={ss['upload_count']}")

    # 10) 租户隔离：B 看不到 A 的视频，删不了 A 的视频（跨租户删 → 403）
    assert c.get("/api/videos", params={"type": "mother"}, headers=B).json()["data"]["total"] == 0
    assert c.delete(f"/api/videos/{vid_ids[2]}", headers=B).status_code == 403
    assert c.get("/api/videos", params={"type": "mother"}, headers=A).json()["data"]["total"] == 3
    print("  ✔ 租户隔离：B 看不到 A 的文件；跨租户删除 → 403")

    # 11) 自动清理：写一条已过期 viral，跑 cleanup → 文件删 + expired
    from services import storage_service
    from datetime import datetime, timedelta
    from models import Video
    s = _db.SessionLocal()
    keep = s.query(Video).filter(Video.tenant_id == "tenantA", Video.type == "viral",
                                 Video.storage_status == "active").first()
    keep.expires_at = datetime.utcnow() - timedelta(days=1)
    s.commit()
    kid = keep.id
    s.close()
    kpath = os.path.join(_STORAGE, "viral", f"{kid}.mp4")
    res = storage_service.run_cleanup(_db.SessionLocal())
    assert res["videos_expired"] >= 1, res
    assert not os.path.exists(kpath), "过期文件应被清理"
    print(f"  ✔ 自动清理：过期文件删除 + 标记 expired（videos_expired={res['videos_expired']}）")

    # 12) Patch6 权限体系不受影响：bootstrap + 登录带 role + /api/me
    code = c.post("/api/admin/invite/generate", json={"count": 1}, headers={"X-Admin-Key": "K"}).json()["data"]["items"][0]["code"]
    c.post("/api/admin/bootstrap", json={"phone": "13800000001"}, headers={"X-Admin-Key": "K"})
    login = c.post("/api/auth/login", json={"phone": "13800000001", "invite_code": code}).json()["data"]
    assert login["role"] == "super_admin", login
    meh = {"Authorization": f"Bearer {login['token']}"}
    assert c.get("/api/me", headers=meh).json()["data"]["is_admin"] is True
    print("  ✔ Patch6 权限体系不受影响（登录带 role、/api/me 正常）")

    # 13) A台防误触：一句话超额生成被拒
    big = c.post("/api/generate", json={"text": "帮我做100个广州美容院抗衰视频"}, headers=A).json()
    assert big["code"] == 2001 and "最多生成" in big["message"], big
    print("  ✔ A台防误触：一句话超额批量生成被拒（2001）")

    _db.engine.dispose()
    if os.path.exists("./_v4p0_test.db"):
        os.remove("./_v4p0_test.db")
    print("\n✅ V4 P0 ALL PASSED")


if __name__ == "__main__":
    main()
