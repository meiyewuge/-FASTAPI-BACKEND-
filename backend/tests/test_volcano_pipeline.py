"""火山 Doubao Seedance 全链路测试（HTTP 用 mock 桩，无需真实 key）。

覆盖：A台生成 / B台裂变 / task轮询 / mock fallback / 成本记录(provider+store_id+duration) / AK-SK 签名。
跑法：
  cd backend && python -m pytest tests/test_volcano_pipeline.py -q
  或   cd backend && python tests/test_volcano_pipeline.py
"""
import os
import subprocess
import sys
import tempfile

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
os.environ["DATABASE_URL"] = "sqlite:///./_pipeline_test.db"

import httpx

import config
import db as _db

_TMP_STORAGE = os.path.join(tempfile.mkdtemp(), "videos")


def _fresh_app():
    _db.engine.dispose()  # 关闭池中连接，避免删文件后复用旧连接报 readonly
    for f in ["./_pipeline_test.db"]:
        if os.path.exists(f):
            os.remove(f)
    config.settings.poll_interval = 0
    config.settings.provider_timeout = 5
    config.settings.video_api_key = "test-key"
    config.settings.video_fallback = True
    config.settings.provider_retries = 3
    config.settings.video_provider = "volcano_seedance"
    config.settings.storage_dir = _TMP_STORAGE
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


def _stub_ok():
    state = {"n": 0}

    def post(url, **kw):
        assert url.endswith("/api/v3/contents/generations/tasks")
        assert "Bearer test-key" == kw["headers"]["Authorization"]
        return _Resp({"id": "task-1"})

    def get(url, **kw):
        state["n"] += 1
        if state["n"] < 2:
            return _Resp({"status": "running"})
        return _Resp({"status": "succeeded",
                      "content": {"video_url": "https://ark.cdn/v.mp4", "duration": 8}})

    httpx.post, httpx.get = post, get


class _Resp:
    def __init__(self, p): self._p = p
    def raise_for_status(self): pass
    def json(self): return self._p


def test_a_pipeline_and_cost():
    c = _fresh_app()
    _stub_ok()
    r = c.post("/api/generate", json={"text": "做2个广州医美抗衰视频"})
    tasks = r.json()["data"]["plan"]["task_ids"]
    assert len(tasks) == 2
    for tid in tasks:
        t = c.get(f"/api/tasks/{tid}").json()["data"]
        assert t["status"] == "done"
        assert t["result"]["videos"][0]["download_url"] == "https://ark.cdn/v.mp4"
    # 成本：provider + store_id + duration
    from models import CostRecord
    s = _db.SessionLocal()
    recs = s.query(CostRecord).filter(CostRecord.api_name == "video.generate.a").all()
    s.close()
    assert {r.provider for r in recs} == {"volcano_seedance"}
    assert all(r.store_id is not None for r in recs)
    assert all(r.duration == 8 for r in recs)


def test_b_remix_pipeline():
    # B9：B台 = 纯本地 ffmpeg 裂变，需母视频本地文件
    c = _fresh_app()
    _stub_ok()
    c.post("/api/generate", json={"text": "做1个杭州养生视频"})
    mid = c.get("/api/videos", params={"type": "mother"}).json()["data"]["items"][0]["video_id"]
    mother_dir = os.path.join(_TMP_STORAGE, "mother")
    os.makedirs(mother_dir, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=teal:s=640x360:d=4",
                    "-pix_fmt", "yuv420p", os.path.join(mother_dir, f"{mid}.mp4")],
                   check=True, capture_output=True)
    tb = c.post("/api/b/generate", json={"source_video_id": mid, "count": 5}).json()["data"]["task_id"]
    res = c.get(f"/api/tasks/{tb}").json()["data"]
    assert res["status"] == "done" and len(res["result"]["videos"]) == 5
    # B台本地裂变 0 成本
    from cost_engine import ledger
    rows = ledger.by_provider(_db.SessionLocal(), "default")
    assert any(r["provider"] == "local_ffmpeg" and r["cost"] == 0.0 for r in rows)


def test_mock_fallback_on_failure():
    c = _fresh_app()
    _stub_ok()

    def boom(url, **kw):
        raise httpx.HTTPError("down")

    httpx.post = boom  # 火山提交全失败
    r = c.post("/api/a/generate", json={"prompt": "兜底"})
    tid = r.json()["data"]["task_id"]
    t = c.get(f"/api/tasks/{tid}").json()["data"]
    assert "mock.cdn" in t["result"]["videos"][0]["download_url"]
    from models import CostRecord
    s = _db.SessionLocal()
    last = s.query(CostRecord).order_by(CostRecord.id.desc()).first()
    s.close()
    assert last.provider == "mock"


def test_two_providers_split():
    # volcano_seedance = Bearer；volcano_legacy = AK/SK 签名（双 provider，不混用）
    config.settings.video_api_key = "ark-key"
    config.settings.volc_ak = "AKID"
    config.settings.volc_sk = "SECRET"
    from utils.volcano_doubao_provider import VolcanoLegacyProvider, VolcanoSeedanceProvider

    sd = VolcanoSeedanceProvider()._auth_headers("POST", "https://x/api", b"{}")
    assert sd["Authorization"] == "Bearer ark-key"

    lg = VolcanoLegacyProvider()._auth_headers("POST", "https://x/api", b"{}")
    assert lg["Authorization"].startswith("HMAC-SHA256 Credential=AKID/")
    assert "X-Date" in lg and "X-Content-Sha256" in lg


def test_aksk_signature_deterministic():
    from datetime import datetime, timezone
    from utils import auth_sign
    now = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    h1 = auth_sign.signed_headers("POST", "https://ark.cn-beijing.volces.com/api/v3/x",
                                  b'{"a":1}', "AKID", "SECRET", now=now)
    h2 = auth_sign.signed_headers("POST", "https://ark.cn-beijing.volces.com/api/v3/x",
                                  b'{"a":1}', "AKID", "SECRET", now=now)
    assert h1 == h2                                   # 确定性
    assert h1["X-Date"] == "20260624T120000Z"
    assert h1["Authorization"].startswith("HMAC-SHA256 Credential=AKID/20260624/cn-beijing/ark/request")
    assert "Signature=" in h1["Authorization"] and len(h1["X-Content-Sha256"]) == 64


if __name__ == "__main__":
    for fn in [test_a_pipeline_and_cost, test_b_remix_pipeline,
               test_mock_fallback_on_failure, test_two_providers_split,
               test_aksk_signature_deterministic]:
        fn()
        print(f"  ✔ {fn.__name__}")
    if os.path.exists("./_pipeline_test.db"):
        os.remove("./_pipeline_test.db")
    print("\n✅ test_volcano_pipeline ALL PASSED")
