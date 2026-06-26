"""Patch5 验证：订阅/试用字段 + GET /api/subscription/status + A台扣减/B台不扣。

跑法：cd backend && python tests/verify_patch5.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
os.environ["DATABASE_URL"] = "sqlite:///./_patch5_test.db"

import config
import db as _db

_TMP = os.path.join(tempfile.mkdtemp(), "videos")


def _client():
    _db.engine.dispose()
    if os.path.exists("./_patch5_test.db"):
        os.remove("./_patch5_test.db")
    config.settings.auth_required = True
    config.settings.jwt_secret = "test-secret"
    config.settings.video_provider = "mock"
    config.settings.storage_dir = _TMP
    # P1.1 提速：缩小裂变目标时长/分辨率（仅测试，不改生产口径）
    config.settings.b_remix_target_lo = 2.0
    config.settings.b_remix_target_hi = 4.0
    config.settings.b_remix_width = 320
    config.settings.b_remix_height = 240
    config.settings.storage_base_url = "https://test.local/static/videos"
    from fastapi.testclient import TestClient
    from main import app
    from utils import jwt_util
    _db.init_db()
    token = jwt_util.encode({"tenant_id": "default"}, config.settings.jwt_secret)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def _make_mp4(path):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=320x240:d=1",
         "-pix_fmt", "yuv420p", path],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def main():
    c = _client()

    # 默认试用态 + 默认余量 3
    st = c.get("/api/subscription/status").json()["data"]
    assert st["status"] == "trial", st
    assert st["trial_remaining"] == 3, st
    assert "quota_remaining" in st
    print(f"  ✔ 初始：status=trial, trial_remaining={st['trial_remaining']}, quota_remaining={st['quota_remaining']}")

    # A台生成一条 → 扣减 1
    r = c.post("/api/a/generate", json={"prompt": "试用扣减测试"})
    assert r.json()["code"] == 0, r.json()
    st = c.get("/api/subscription/status").json()["data"]
    assert st["trial_remaining"] == 2, st
    print(f"  ✔ A台生成1条 → trial_remaining={st['trial_remaining']}（扣减1）")

    # 准备一条本地母视频，供 B台裂变
    from models import Video
    s = _db.SessionLocal()
    m = Video(tenant_id="default", type="mother", title="母", cdn_url="http://x/m.mp4")
    s.add(m); s.commit(); mid = m.id; s.close()
    os.makedirs(os.path.join(_TMP, "mother"), exist_ok=True)
    _make_mp4(os.path.join(_TMP, "mother", f"{mid}.mp4"))

    # B台裂变 → 试用余量不变（B台不扣）
    before = c.get("/api/subscription/status").json()["data"]["trial_remaining"]
    r = c.post("/api/b/generate", json={"source_video_id": mid, "count": 2})
    assert r.json()["code"] == 0, r.json()
    after = c.get("/api/subscription/status").json()["data"]["trial_remaining"]
    assert before == after == 2, (before, after)
    print(f"  ✔ B台裂变2条 → trial_remaining={after}（不扣，仅A台扣）")

    # 扣到 0 后不再为负
    c.post("/api/a/generate", json={"prompt": "再来"})
    c.post("/api/a/generate", json={"prompt": "再来"})
    c.post("/api/a/generate", json={"prompt": "超额"})  # 已 0，不应为负
    st = c.get("/api/subscription/status").json()["data"]
    assert st["trial_remaining"] == 0, st
    print(f"  ✔ 连续 A台至耗尽 → trial_remaining={st['trial_remaining']}（不为负）")

    _db.engine.dispose()
    if os.path.exists("./_patch5_test.db"):
        os.remove("./_patch5_test.db")
    print("\n✅ Patch5 订阅/试用 ALL PASSED")


if __name__ == "__main__":
    main()
