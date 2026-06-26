"""V4 P1 B台裂变验证：duration_seconds 硬门槛 + source_pool 优先 + 1:10（30/40/50）+ 0 成本。

覆盖（对应吴哥 16 点）：
1  2 个合格源 → 失败（门槛）
2  3 个合格源 → total_outputs=30
3  4 个合格源 → 40
4  5 个合格源 → 50
5  6 个合格源 → 只用前 5 个，total=50，返回 ignored
6  duration_seconds=NULL 不计入合格源
7  duration_seconds<30 不计入合格源
8  source_video_ids 跨租户失败
9  旧字段 sources 仍兼容
10 裂变结果进入 viral 列表（type=viral & batch_id）
11 expires_at = created_at + 5 天
12 B台成本为 0
13 不调用火山（provider=local_ffmpeg）
14 /api/compose 权限仍 require_auth
15 Patch6 管理员权限不受影响
16 回归在单独脚本
"""
import os
import subprocess
import sys
import tempfile
from datetime import datetime

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
os.environ["DATABASE_URL"] = "sqlite:///./_v4p1_test.db"

import config
import db as _db

_STORAGE = os.path.join(tempfile.mkdtemp(), "videos")


def _mp4(path, dur=2):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=red:s=320x240:d={dur}",
         "-pix_fmt", "yuv420p", path],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _client():
    _db.engine.dispose()
    if os.path.exists("./_v4p1_test.db"):
        os.remove("./_v4p1_test.db")
    config.settings.auth_required = True
    config.settings.jwt_secret = "s"
    config.settings.admin_key = "K"
    config.settings.storage_dir = _STORAGE
    # P1.1 提速：缩小裂变目标时长/分辨率（仅测试，不改生产口径）
    config.settings.b_remix_target_lo = 2.0
    config.settings.b_remix_target_hi = 4.0
    config.settings.b_remix_width = 320
    config.settings.b_remix_height = 240
    config.settings.storage_base_url = "https://test.local/static/videos"
    config.settings.viral_retention_days = 5
    from fastapi.testclient import TestClient
    from main import app
    _db.init_db()
    return TestClient(app)


def _hdr(tenant, phone="13800000000"):
    from utils import jwt_util
    return {"Authorization": f"Bearer {jwt_util.encode({'tenant_id': tenant, 'phone': phone}, 's')}"}


def _mk_source(tenant, dur_seconds):
    """建一条母视频（duration_seconds=dur_seconds），写本地文件供裂变。"""
    from models import Video
    s = _db.SessionLocal()
    v = Video(tenant_id=tenant, type="mother", source_type="uploaded",
              storage_status="active", title="src", duration_seconds=dur_seconds)
    s.add(v); s.commit(); vid = v.id; s.close()
    os.makedirs(os.path.join(_STORAGE, "mother"), exist_ok=True)
    _mp4(os.path.join(_STORAGE, "mother", f"{vid}.mp4"))
    return vid


def _batch(c, hdr, ids=None, **extra):
    body = {"prompt": "抗衰主题", **extra}
    if ids is not None:
        body["source_video_ids"] = ids
    return c.post("/api/b/batch-generate", json=body, headers=hdr).json()


def main():
    c = _client()
    A = _hdr("tenantA")
    B = _hdr("tenantB")

    # 1) 2 个合格源 → 失败
    two = [_mk_source("tenantA", 40) for _ in range(2)]
    r = _batch(c, A, two)
    assert r["code"] == 2001 and "至少上传 3" in r["message"], r
    print("  ✔ 2 个合格源 → 2001（门槛拒绝）")

    # 加 1 个合格 → 3 个
    three = two + [_mk_source("tenantA", 35)]
    r = _batch(c, A, three)["data"]
    assert r["total_outputs"] == 30 and r["source_count"] == 3 and r["cost"] == 0, r
    print("  ✔ 3 个合格源 → total_outputs=30, cost=0")
    batch_id = r["batch_id"]

    # 3) 4 个 → 40
    four = three + [_mk_source("tenantA", 31)]
    r = _batch(c, A, four)["data"]
    assert r["total_outputs"] == 40 and r["source_count"] == 4, r
    print("  ✔ 4 个合格源 → total_outputs=40")

    # 4) 5 个 → 50
    five = four + [_mk_source("tenantA", 60)]
    r = _batch(c, A, five)["data"]
    assert r["total_outputs"] == 50 and r["source_count"] == 5, r
    print("  ✔ 5 个合格源 → total_outputs=50")

    # 5) 6 个 → 只用前 5 个，total=50，返回 ignored
    six = five + [_mk_source("tenantA", 45)]
    r = _batch(c, A, six)["data"]
    assert r["total_outputs"] == 50 and r["source_count"] == 5, r
    assert r["ignored_source_video_ids"] == [six[5]], r   # 第6个（传入顺序最后）被忽略
    print(f"  ✔ 6 个合格源 → 只用前5, total=50, ignored={r['ignored_source_video_ids']}")

    # 6) duration_seconds=NULL 不计入合格源
    nullsrc = _mk_source("tenantA", 40)
    from models import Video
    s = _db.SessionLocal(); s.get(Video, nullsrc).duration_seconds = None; s.commit(); s.close()
    short1 = _mk_source("tenantA", 20)   # <30
    # 仅用 [null, short, 1个合格] → 合格仅1个 → 失败
    one_ok = _mk_source("tenantA", 33)
    r = _batch(c, A, [nullsrc, short1, one_ok])
    assert r["code"] == 2001, r
    print("  ✔ NULL 时长不计入合格源（含 NULL 后合格<3 → 2001）")

    # 7) duration_seconds<30 不计入
    short2 = _mk_source("tenantA", 10)
    short3 = _mk_source("tenantA", 29)
    r = _batch(c, A, [short1, short2, short3, one_ok])
    assert r["code"] == 2001, r   # 仅 one_ok 合格
    print("  ✔ <30 秒不计入合格源（→ 2001）")

    # 8) 跨租户失败：tenantB 用 tenantA 的合格源 → 0 合格 → 2001
    r = _batch(c, B, five)
    assert r["code"] == 2001, r
    print("  ✔ source_video_ids 跨租户 → 2001（不混源）")

    # 9) 旧字段 sources 兼容
    r = c.post("/api/b/batch-generate",
               json={"prompt": "兼容", "sources": [{"source_video_id": i, "count": 10} for i in three]},
               headers=A).json()["data"]
    assert r["total_outputs"] == 30 and r["source_count"] == 3, r
    print("  ✔ 旧字段 sources 仍兼容（仅兼容）")

    # 10) 裂变结果进入 viral 列表（用最早 batch_id=30 条）
    st = c.get(f"/api/b/batch/{batch_id}", headers=A).json()["data"]
    assert st["status"] == "done" and st["completed"] == 30 and st["total_outputs"] == 30, st
    assert len(st["video_ids"]) == 30, st
    vl = c.get("/api/videos", params={"type": "viral", "batch_id": batch_id}, headers=A).json()["data"]
    assert vl["total"] == 30, vl
    assert all(it["source_type"] == "remixed" and it["type"] == "viral" for it in vl["items"]), vl
    print("  ✔ 裂变结果进入 viral 列表（batch done, 30 条, source_type=remixed）")

    # 11) expires_at = created_at + 5 天
    s = _db.SessionLocal()
    vv = s.query(Video).filter(Video.batch_id == batch_id, Video.type == "viral").first()
    delta_days = (vv.expires_at - vv.created_at).days
    s.close()
    assert 4 <= delta_days <= 5, delta_days
    print(f"  ✔ 裂变视频 expires_at ≈ created_at + 5 天（delta={delta_days}d）")

    # 12/13) 成本 0 + provider=local_ffmpeg
    from models import CostRecord
    s = _db.SessionLocal()
    recs = s.query(CostRecord).filter(CostRecord.tenant_id == "tenantA",
                                      CostRecord.api_name == "video.remix.b").all()
    amt = sum(x.amount or 0 for x in recs)
    providers = {x.provider for x in recs}
    s.close()
    assert amt == 0, amt
    assert providers == {"local_ffmpeg"}, providers
    print("  ✔ B台成本=0 且 provider=local_ffmpeg（不调火山）")

    # 14) /api/compose 权限 require_auth：无 JWT→401，带 JWT→受理
    assert c.post("/api/compose", json={"prompt": "x", "total_seconds": 15}).status_code == 401
    print("  ✔ /api/compose 无 JWT → 401（require_auth）")

    # 15) Patch6 管理员权限不受影响
    code = c.post("/api/admin/invite/generate", json={"count": 1}, headers={"X-Admin-Key": "K"}).json()["data"]["items"][0]["code"]
    c.post("/api/admin/bootstrap", json={"phone": "13700000000"}, headers={"X-Admin-Key": "K"})
    login = c.post("/api/auth/login", json={"phone": "13700000000", "invite_code": code}).json()["data"]
    assert login["role"] == "super_admin", login
    print("  ✔ Patch6 管理员权限不受影响（bootstrap+登录 role=super_admin）")

    _db.engine.dispose()
    if os.path.exists("./_v4p1_test.db"):
        os.remove("./_v4p1_test.db")
    print("\n✅ V4 P1 B台裂变 ALL PASSED")


if __name__ == "__main__":
    main()
