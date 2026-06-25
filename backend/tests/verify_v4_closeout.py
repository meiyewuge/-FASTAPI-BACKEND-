"""V4 P0 收口验证：删除视频权限（租户隔离 + super_admin 全局）+ storage/status 分角色。

覆盖：
- user 删除自己视频成功；删除后文件不存在 + DB storage_status=deleted
- user 删除其他 tenant 视频失败（403）
- super_admin 删除任意 tenant 视频成功
- user 只能看到 tenant scope（无全局磁盘）
- invite_admin 看不到全局（tenant scope）
- super_admin 看到 global scope（磁盘 + tenant_summary）
"""
import os
import subprocess
import sys
import tempfile

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
os.environ["DATABASE_URL"] = "sqlite:///./_v4closeout_test.db"

import config
import db as _db

_STORAGE = os.path.join(tempfile.mkdtemp(), "videos")


def _mp4(path):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=green:s=320x240:d=1",
         "-pix_fmt", "yuv420p", path],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _client():
    _db.engine.dispose()
    if os.path.exists("./_v4closeout_test.db"):
        os.remove("./_v4closeout_test.db")
    config.settings.auth_required = True
    config.settings.jwt_secret = "s"
    config.settings.admin_key = "K"
    config.settings.storage_dir = _STORAGE
    config.settings.storage_base_url = "https://test.local/static/videos"
    from fastapi.testclient import TestClient
    from main import app
    _db.init_db()
    return TestClient(app)


def _tok(tenant, phone, role="user"):
    from utils import jwt_util
    return {"Authorization": f"Bearer {jwt_util.encode({'tenant_id': tenant, 'phone': phone, 'role': role}, 's')}"}


def _mother(tenant, vtype="mother"):
    from models import Video
    s = _db.SessionLocal()
    v = Video(tenant_id=tenant, type=vtype, source_type="uploaded", title="v")
    s.add(v); s.commit(); vid = v.id; s.close()
    subdir = "viral" if vtype == "viral" else "mother"
    os.makedirs(os.path.join(_STORAGE, subdir), exist_ok=True)
    _mp4(os.path.join(_STORAGE, subdir, f"{vid}.mp4"))
    return vid


def _status(vid):
    from models import Video
    s = _db.SessionLocal()
    st = s.get(Video, vid).storage_status
    s.close()
    return st


def main():
    c = _client()
    userA = _tok("tenantA", "13800000001")
    userB = _tok("tenantB", "13900000002")

    # bootstrap super_admin（吴哥）
    code = c.post("/api/admin/invite/generate", json={"count": 1}, headers={"X-Admin-Key": "K"}).json()["data"]["items"][0]["code"]
    c.post("/api/admin/bootstrap", json={"phone": "13700000000"}, headers={"X-Admin-Key": "K"})
    login = c.post("/api/auth/login", json={"phone": "13700000000", "invite_code": code}).json()["data"]
    assert login["role"] == "super_admin", login
    SA = {"Authorization": f"Bearer {login['token']}"}

    # ---- 删除权限 ----
    a1 = _mother("tenantA")
    a2 = _mother("tenantA", "viral")
    b1 = _mother("tenantB")

    # 1) user 删自己视频成功 + 文件删除 + DB deleted
    fp = os.path.join(_STORAGE, "mother", f"{a1}.mp4")
    assert os.path.exists(fp)
    assert c.delete(f"/api/videos/{a1}", headers=userA).json()["code"] == 0
    assert not os.path.exists(fp), "文件应删除"
    assert _status(a1) == "deleted"
    print("  ✔ user 删自己视频成功（文件删除 + DB storage_status=deleted）")

    # 2) user 删其他 tenant 视频失败（403）
    assert c.delete(f"/api/videos/{b1}", headers=userA).status_code == 403
    assert _status(b1) == "active", "跨租户删除不得生效"
    print("  ✔ user 删其他 tenant 视频 → 403（且未生效）")

    # 3) super_admin 删任意 tenant 视频成功
    bfp = os.path.join(_STORAGE, "mother", f"{b1}.mp4")
    assert c.delete(f"/api/videos/{b1}", headers=SA).json()["code"] == 0
    assert not os.path.exists(bfp) and _status(b1) == "deleted"
    print("  ✔ super_admin 删任意租户视频成功")

    # 不存在 → 3001
    assert c.delete("/api/videos/999999", headers=SA).json()["code"] == 3001
    print("  ✔ 删不存在视频 → 3001")

    # ---- storage/status 分角色 ----
    # 4) user → tenant scope，无全局磁盘
    su = c.get("/api/storage/status", headers=userA).json()["data"]
    assert su["scope"] == "tenant" and "disk_total_gb" not in su, su
    assert su["tenant_id"] == "tenantA" and "estimated_used_mb" in su, su
    print("  ✔ user → scope=tenant（无全局磁盘，含 estimated_used_mb）")

    # 5) invite_admin → tenant scope（看不到全局）
    c.post("/api/admin/users/grant", json={"phone": "13600000000", "role": "invite_admin"}, headers=SA)
    icode = c.post("/api/admin/invite/generate", json={"count": 1}, headers=SA).json()["data"]["items"][0]["code"]
    ia_login = c.post("/api/auth/login", json={"phone": "13600000000", "invite_code": icode}).json()["data"]
    assert ia_login["role"] == "invite_admin", ia_login
    IA = {"Authorization": f"Bearer {ia_login['token']}"}
    sia = c.get("/api/storage/status", headers=IA).json()["data"]
    assert sia["scope"] == "tenant" and "disk_total_gb" not in sia, sia
    print("  ✔ invite_admin → scope=tenant（看不到全局磁盘）")

    # 6) super_admin → global scope（磁盘 + tenant_summary）
    sg = c.get("/api/storage/status", headers=SA).json()["data"]
    assert sg["scope"] == "global", sg
    for k in ("disk_total_gb", "disk_used_gb", "disk_used_percent", "mother_count", "viral_count", "upload_count", "tenant_summary"):
        assert k in sg, sg
    assert isinstance(sg["tenant_summary"], list)
    print(f"  ✔ super_admin → scope=global（磁盘 + tenant_summary，{len(sg['tenant_summary'])} 个租户）")

    _db.engine.dispose()
    if os.path.exists("./_v4closeout_test.db"):
        os.remove("./_v4closeout_test.db")
    print("\n✅ V4 P0 收口（删除权限 + storage 分角色）ALL PASSED")


if __name__ == "__main__":
    main()
