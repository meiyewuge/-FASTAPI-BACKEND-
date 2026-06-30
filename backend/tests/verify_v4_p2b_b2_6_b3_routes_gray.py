"""V4 P2B-B2.6 B3 routes gray gate hotfix 验证。

production 灰度链路：/api/p2b-b/runs 能生成，则 B3 score/get/publish-pool 必须可达（窄门一致）；
simulate 在 production 仍 403。覆盖 8 项：
1 gray=false→B3 403 / 2 不在白名单→403 / 3 满足窄门→score/publish 可访问 / 4 B3_SCORE=false→403 /
5 publish_required=false→403 / 6 simulate production→403 / 7 staging B3 routes 不变 / 8 schema 不变。

跑法：cd backend && SAMPLE_DIR=/path python tests/verify_v4_p2b_b2_6_b3_routes_gray.py
"""
import json
import os
import subprocess
import sys
import tempfile

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
os.environ["DATABASE_URL"] = "sqlite:///./_v4p2bb26r_test.db"

import config
import db as _db

_STORAGE = os.path.join(tempfile.mkdtemp(), "videos")
_SAMPLE_DIR = os.environ.get("SAMPLE_DIR") or os.path.join(tempfile.mkdtemp(), "p2b_b26r_samples")


def _make_source(path, seconds, w=320, h=240, audio=True):
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=s={w}x{h}:d={seconds}:r=30"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"anoisesrc=d={seconds}:c=pink:a=0.7",
                "-f", "lavfi",
                "-i", f"aevalsrc=exprs=0.45*sin(2*PI*3000*t)*lt(mod(t\\,0.05)\\,0.004):d={seconds}:s=44100",
                "-filter_complex", "[1:a][2:a]amix=inputs=2:weights=1 1:normalize=0[a]"]
    cmd += ["-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-map", "0:v", "-map", "[a]", "-c:a", "aac", "-shortest"]
    cmd += [path]
    subprocess.run(cmd, check=True, capture_output=True)


def _client():
    _db.engine.dispose()
    if os.path.exists("./_v4p2bb26r_test.db"):
        os.remove("./_v4p2bb26r_test.db")
    s = config.settings
    s.auth_required = True; s.jwt_secret = "s"; s.admin_key = "K"
    s.app_env = "staging"; s.enable_compose = False
    s.enable_l2_skills = True; s.enable_p2b_real_execution = True
    s.enable_p2b_visible_layer = True; s.enable_p2b_visible_variation = True
    s.enable_p2b_audio_encoding_diff = True; s.enable_p2b_b3_score = True
    s.enable_p2b_visual_diff = True; s.enable_p2b_window_divergence = True
    s.enable_p2b_production_gray = False; s.p2b_gray_tenant_allowlist = []
    s.p2b_gray_daily_run_quota = 100; s.p2b_gray_max_items = 3; s.p2b_b3_publish_required = True
    s.p2b_build_commit = "testcommit"; s.p2b_subtitle_font_path = ""
    s.storage_dir = _STORAGE; s.storage_base_url = "https://test.local/static/videos"
    s.b_remix_target_lo = 25.0; s.b_remix_target_hi = 35.0
    s.b_remix_width = 320; s.b_remix_height = 240; s.b_remix_fps = 30
    from fastapi.testclient import TestClient
    from main import app
    _db.init_db()
    from migrations import p2a_init, p2b_a_init, p2b_b1_init
    p2a_init.run(); p2b_a_init.run(); p2b_b1_init.run()
    return TestClient(app)


def _hdr(t):
    from utils import jwt_util
    return {"Authorization": f"Bearer {jwt_util.encode({'tenant_id': t, 'phone': t}, 's')}"}


def _tables():
    from sqlalchemy import inspect
    return set(inspect(_db.engine).get_table_names())


def _make_mother(tenant, seconds=40):
    from models import Video
    se = _db.SessionLocal()
    v = Video(tenant_id=tenant, type="mother", source_type="uploaded", title="母", duration_seconds=seconds)
    se.add(v); se.commit(); vid = v.id; se.close()
    os.makedirs(os.path.join(_STORAGE, "mother"), exist_ok=True)
    _make_source(os.path.join(_STORAGE, "mother", f"{vid}.mp4"), seconds, audio=True)
    return vid


def main():
    os.makedirs(_SAMPLE_DIR, exist_ok=True)
    c = _client(); A = _hdr("tenantA")
    tables0 = _tables()

    # 前置：staging 跑 1 run + B3（供 production gray 下 score/publish 访问）
    dp = c.post("/api/compose/preview",
                json={"prompt": "达芙荻丽修复精华，痛点皱纹暗沉，产品展示质地，效果对比7天，品牌定格，关注领取试用装",
                      "style": "premium", "ratio": "9:16", "duration": 30, "resolution": "1080p"},
                headers=A).json()["data"]["director_plan_id"]
    po = c.post("/api/production-orders",
                json={"director_plan_id": dp, "scenario": "product_seeding", "platform": "douyin"},
                headers=A).json()["data"]["production_order_id"]
    c.post("/api/p2b/execution-plans", json={"production_order_id": po}, headers=A)
    elig = c.get(f"/api/p2b-b/eligible-plans/{po}", headers=A).json()["data"]["items"]
    pick = {}
    for e in elig:
        if e["group_type"] in ("pain_first", "selling_first", "result_close") and e["group_type"] not in pick:
            pick[e["group_type"]] = e["execution_plan_id"]
    plan_ids = [pick["pain_first"], pick["selling_first"], pick["result_close"]]
    src_id = _make_mother("tenantA", 40)
    run = c.post("/api/p2b-b/runs", json={"production_order_id": po, "execution_plan_ids": plan_ids,
                 "source_video_id": src_id, "max_items": 3}, headers=A).json()
    run_id = run["data"]["run_id"]

    # ---- (7) staging B3 routes 行为不变：score/get/publish 正常 ----
    assert c.post("/api/p2b-b3/score", json={"run_id": run_id}, headers=A).json()["code"] == 0
    assert c.get(f"/api/p2b-b3/score/{run_id}", headers=A).json()["code"] == 0
    assert c.get(f"/api/p2b-b3/publish-pool/{run_id}", headers=A).json()["code"] == 0
    assert c.post("/api/p2b-b3/simulate", json={"production_order_id": po, "n": 50}, headers=A).json()["code"] == 0
    print("  ✔ (7) staging B3 routes（score/get/publish/simulate）行为不变")

    s = config.settings
    s.app_env = "production"
    SC = lambda: c.post("/api/p2b-b3/score", json={"run_id": run_id}, headers=A)
    GET = lambda: c.get(f"/api/p2b-b3/score/{run_id}", headers=A)
    PP = lambda: c.get(f"/api/p2b-b3/publish-pool/{run_id}", headers=A)
    SIM = lambda: c.post("/api/p2b-b3/simulate", json={"production_order_id": po, "n": 50}, headers=A)

    # ---- (1) gray=false → B3 routes 仍 403 ----
    s.enable_p2b_production_gray = False; s.p2b_gray_tenant_allowlist = ["tenantA"]
    assert SC().status_code == 403 and GET().status_code == 403 and PP().status_code == 403
    print("  ✔ (1) production gray=false → B3 score/get/publish 均 403")

    # ---- (2) gray=true 但不在白名单 → 403 ----
    s.enable_p2b_production_gray = True; s.p2b_gray_tenant_allowlist = ["other"]
    assert SC().status_code == 403 and PP().status_code == 403
    print("  ✔ (2) gray=true 但 tenant 不在白名单 → B3 routes 403")

    # ---- (4) B3_SCORE=false → 403 ----
    s.p2b_gray_tenant_allowlist = ["tenantA"]; s.enable_p2b_b3_score = False
    assert SC().status_code == 403 and PP().status_code == 403
    s.enable_p2b_b3_score = True
    print("  ✔ (4) gray=true 但 ENABLE_P2B_B3_SCORE=false → B3 routes 403")

    # ---- (5) publish_required=false → 仍不允许灰度（403）----
    s.p2b_b3_publish_required = False
    assert SC().status_code == 403 and PP().status_code == 403
    s.p2b_b3_publish_required = True
    print("  ✔ (5) gray=true 但 P2B_B3_PUBLISH_REQUIRED=false → B3 routes 403（不允许灰度发布）")

    # ---- (3) 满足窄门 → score/get/publish 可访问 ----
    assert SC().json()["code"] == 0, SC().json()
    assert GET().json()["code"] == 0
    ppr = PP().json(); assert ppr["code"] == 0 and ppr["data"]["has_b3_score"] is True
    # publish_pool 仍守强制闸门：只 pass_to_publish_pool；blocked 不在 publishable
    assert set(ppr["data"]["publishable_video_ids"]).isdisjoint(set(ppr["data"]["blocked_video_ids"]))
    print(f"  ✔ (3) 满足窄门(gray+白名单+B3+publish_required) → B3 score/get/publish 可访问；publishable={ppr['data']['publishable_video_ids']}")

    # ---- (6) simulate 在 production 仍 403（不进灰度窄门）----
    assert SIM().status_code == 403, "simulate 在 production 必须 403"
    print("  ✔ (6) simulate 在 production 仍 403（不进灰度窄门）")

    s.app_env = "staging"
    # ---- (8) schema 不变 ----
    assert _tables() == tables0, "不得新增表/改 schema"
    print("  ✔ (8) 不新增表 / DB schema 不变")

    _db.engine.dispose()
    if os.path.exists("./_v4p2bb26r_test.db"):
        os.remove("./_v4p2bb26r_test.db")
    print("\n✅ V4 P2B-B2.6 B3 routes gray gate ALL PASSED（8/8）")


if __name__ == "__main__":
    main()
