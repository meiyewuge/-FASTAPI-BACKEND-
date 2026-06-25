"""B9 确认测试：B台 = 纯本地 ffmpeg 裂变，不调火山，0 成本。

跑法：cd backend && python tests/test_b9_local_remix.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
os.environ["DATABASE_URL"] = "sqlite:///./_b9_confirm.db"


def test_b9_local_ffmpeg_remix():
    for f in ["./_b9_confirm.db"]:
        if os.path.exists(f):
            os.remove(f)
    work = tempfile.mkdtemp()
    src = os.path.join(work, "m.mp4")
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=teal:s=1280x720:d=5",
                    "-pix_fmt", "yuv420p", src], check=True, capture_output=True)

    import config
    config.settings.storage_dir = os.path.join(work, "storage", "videos")
    config.settings.storage_base_url = "https://video.beautypeaceai.com/static/videos"
    config.settings.video_provider = "mock"  # B台不应调用它

    import db
    db.engine.dispose()
    db.init_db()
    from models import CostRecord, Video
    s = db.SessionLocal()
    m = Video(tenant_id="default", type="mother", title="母视频", cdn_url="http://x/m.mp4")
    s.add(m); s.commit(); mid = m.id; s.close()
    os.makedirs(os.path.join(config.settings.storage_dir, "mother"), exist_ok=True)
    shutil.copy(src, os.path.join(config.settings.storage_dir, "mother", f"{mid}.mp4"))

    from fastapi.testclient import TestClient
    from main import app
    c = TestClient(app)
    tb = c.post("/api/b/generate", json={"source_video_id": mid, "count": 3}).json()["data"]["task_id"]
    res = c.get(f"/api/tasks/{tb}").json()["data"]
    assert res["status"] == "done" and len(res["result"]["videos"]) == 3

    for v in c.get("/api/videos", params={"type": "viral"}).json()["data"]["items"]:
        fp = os.path.join(config.settings.storage_dir, "viral", f"{v['video_id']}.mp4")
        assert os.path.exists(fp) and os.path.getsize(fp) > 0
        assert v["download_url"].endswith(f"/viral/{v['video_id']}.mp4")
        assert "mock.cdn" not in (v["download_url"] or "")

    s = db.SessionLocal()
    recs = s.query(CostRecord).filter(CostRecord.api_name == "video.remix.b").all()
    s.close()
    assert sum(r.amount for r in recs) == 0.0
    assert {r.provider for r in recs} == {"local_ffmpeg"}

    import inspect

    import b_engine.remixer as rm
    assert "get_provider" not in inspect.getsource(rm)  # B台不依赖 provider
    os.remove("./_b9_confirm.db")


if __name__ == "__main__":
    test_b9_local_ffmpeg_remix()
    print("✅ B9 确认：B台本地 ffmpeg 裂变 / 0成本 / 不调火山 / provider=local_ffmpeg")
