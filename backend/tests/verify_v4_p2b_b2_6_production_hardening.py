"""V4 P2B-B2.6 生产加固 验证（production 灰度窄门 + duplicate 拦截 + B3 强制闸门 + alerts/degraded）。

覆盖 13 项（14/15 为 DB 初始化/rollback SOP，见报告，非代码可测）：
1 gray=false→403 / 2 不在白名单→403 / 3 超配额→403 / 4 max_items>3→403 / 5 B3_SCORE=false→403 /
6 满足窄门→放行 / 7 duplicate 拦截不创建新 run / 8 force 跳过拦截 / 9 无 B3 不可发布 /
10 blocked/quality_fail/unknown 不进 publishable / 11 degraded_rate 汇总 / 12 b3_alerts 写入 / 13 schema 不变。

跑法：cd backend && SAMPLE_DIR=/path python tests/verify_v4_p2b_b2_6_production_hardening.py
"""
import json
import os
import subprocess
import sys
import tempfile

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
os.environ["DATABASE_URL"] = "sqlite:///./_v4p2bb26_test.db"

import config
import db as _db

_STORAGE = os.path.join(tempfile.mkdtemp(), "videos")
_SAMPLE_DIR = os.environ.get("SAMPLE_DIR") or os.path.join(tempfile.mkdtemp(), "p2b_b26_samples")


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
    if os.path.exists("./_v4p2bb26_test.db"):
        os.remove("./_v4p2bb26_test.db")
    s = config.settings
    s.auth_required = True; s.jwt_secret = "s"; s.admin_key = "K"
    s.app_env = "staging"; s.enable_compose = False
    s.enable_l2_skills = True; s.enable_p2b_real_execution = True
    s.enable_p2b_visible_layer = True; s.enable_p2b_visible_variation = True
    s.enable_p2b_audio_encoding_diff = True; s.enable_p2b_b3_score = True
    s.enable_p2b_visual_diff = True; s.enable_p2b_window_divergence = True
    # B2.6 默认安全态
    s.enable_p2b_production_gray = False; s.p2b_gray_tenant_allowlist = []
    s.p2b_gray_daily_run_quota = 3; s.p2b_gray_max_items = 3; s.p2b_b3_publish_required = True
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
    from services import p2b_b_service as bsvc

    # 前置：po + plans + mother（staging）
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
    body = lambda **kw: {"production_order_id": po, "execution_plan_ids": plan_ids,
                         "source_video_id": src_id, "max_items": 3, **kw}

    def _post_runs(extra=None):
        return c.post("/api/p2b-b/runs", json=body(**(extra or {})), headers=A)

    # ---- 9: 先建一个 staging run + B3，用于 publish/degraded/alerts/publish-no-b3 ----
    run = _post_runs().json(); assert run["code"] == 0 and run["data"]["completed"] == 3, run
    run_id = run["data"]["run_id"]
    # publish_pool 未跑 B3 → 不可发布
    pp0 = c.get(f"/api/p2b-b3/publish-pool/{run_id}", headers=A).json()["data"]
    assert pp0["has_b3_score"] is False and pp0["eligible"] is False, pp0
    assert pp0["publish_required"] is True
    print("  ✔ (9) 未跑 B3 → publish_pool 不可发布（has_b3_score=False, eligible=False）")

    b3 = c.post("/api/p2b-b3/score", json={"run_id": run_id}, headers=A).json()["data"]
    bs = b3["batch_summary"]
    # ---- 11: degraded_rate 汇总 ----
    for kk in ("degraded_count", "degraded_rate", "degraded_reasons"):
        assert kk in bs, f"batch_summary 缺 {kk}"
    assert 0.0 <= bs["degraded_rate"] <= 1.0
    print(f"  ✔ (11) degraded_rate 汇总：count={bs['degraded_count']} rate={bs['degraded_rate']}")
    # ---- 12: b3_alerts 写入 ----
    al = bs.get("b3_alerts")
    for kk in ("quality_fail", "quality_unknown_rate", "batch_pass_rate_low", "too_similar",
               "degraded_rate", "any_alert"):
        assert al and kk in al, f"b3_alerts 缺 {kk}: {al}"
    from sqlalchemy import text
    se = _db.SessionLocal()
    qj = se.execute(text("SELECT qa_json FROM p2b_execution_run_items WHERE run_id=:r LIMIT 1"),
                    {"r": run_id}).fetchone()
    se.close()
    assert "b3_alerts" in json.loads(qj[0]), "qa_json 应含 b3_alerts"
    print(f"  ✔ (12) b3_alerts 写入 run_items.qa_json：any_alert={al['any_alert']}")
    # ---- 10: publishable 只含 pass_to_publish_pool；blocked 不在 publishable ----
    pp = c.get(f"/api/p2b-b3/publish-pool/{run_id}", headers=A).json()["data"]
    assert pp["has_b3_score"] is True
    pass_ids = [p["video_id"] for p in b3["per_variant"] if p["recommended_action"] == "pass_to_publish_pool"]
    assert sorted(pp["publishable_video_ids"]) == sorted(pass_ids), pp
    assert set(pp["publishable_video_ids"]).isdisjoint(set(pp["blocked_video_ids"])), pp
    assert set(pp["quality_fail_videos"]).isdisjoint(set(pp["publishable_video_ids"])), pp
    print(f"  ✔ (10) publishable={pp['publishable_video_ids']} 不含 blocked/quality_fail（B3 强制闸门）")

    # ---- production 灰度窄门 ----
    s = config.settings
    s.app_env = "production"
    # (1) gray=false → 403
    s.enable_p2b_production_gray = False; s.p2b_gray_tenant_allowlist = ["tenantA"]
    assert _post_runs().status_code == 403, "gray=false 必须 403"
    print("  ✔ (1) production gray=false → 403")
    # (2) gray=true 但不在白名单 → 403
    s.enable_p2b_production_gray = True; s.p2b_gray_tenant_allowlist = ["other"]
    assert _post_runs().status_code == 403, "不在白名单必须 403"
    print("  ✔ (2) gray=true 但 tenant 不在白名单 → 403")
    # (4) gray=true 白名单内但 max_items>gray_max → 403
    s.p2b_gray_tenant_allowlist = ["tenantA"]; s.p2b_gray_max_items = 3
    assert c.post("/api/p2b-b/runs", json=body(max_items=4), headers=A).status_code == 403, "max_items>3 必须 403"
    print("  ✔ (4) gray=true 但 max_items>3 → 403")
    # (5) gray=true 但 B3_SCORE=false → 403
    s.enable_p2b_b3_score = False
    assert _post_runs().status_code == 403, "B3_SCORE=false 必须 403"
    s.enable_p2b_b3_score = True
    print("  ✔ (5) gray=true 但 ENABLE_P2B_B3_SCORE=false → 403")
    # (3) 超配额 → 403（把 quota 设成当前已用数）
    se = _db.SessionLocal(); used = bsvc.today_run_count(se, "tenantA"); se.close()
    s.p2b_gray_daily_run_quota = used
    assert _post_runs().status_code == 403, "超配额必须 403"
    print(f"  ✔ (3) gray=true 但超当日配额（used={used}）→ 403")
    # (6) 满足全部窄门 → 放行执行（quota 放开；用新源避免与前置 staging run 同参）
    s.p2b_gray_daily_run_quota = 100
    src_id2 = _make_mother("tenantA", 40)
    body2 = lambda **kw: {"production_order_id": po, "execution_plan_ids": plan_ids,
                          "source_video_id": src_id2, "max_items": 3, **kw}
    r6 = c.post("/api/p2b-b/runs", json=body2(), headers=A); j6 = r6.json()
    assert r6.status_code == 200 and j6["code"] == 0 and j6["data"].get("completed") == 3, j6
    gray_run_id = j6["data"]["run_id"]
    print(f"  ✔ (6) 满足白名单+配额+B3+max_items≤3 → production 灰度放行执行（run={gray_run_id[:12]}）")

    # ---- (7) duplicate 拦截：同参再发 → 不创建新 run ----
    r7 = c.post("/api/p2b-b/runs", json=body2(), headers=A).json()
    assert r7.get("data", {}).get("duplicate_run") is True, r7
    assert r7["data"]["existing_run_id"] == gray_run_id and r7["data"]["created_new"] is False
    print(f"  ✔ (7) duplicate run 拦截：返回 existing_run_id={r7['data']['existing_run_id'][:12]}，未创建新 run")
    # ---- (8) force=true 跳过拦截 → 创建新 run ----
    r8 = c.post("/api/p2b-b/runs", json=body2(force=True), headers=A).json()
    assert r8["code"] == 0 and r8["data"].get("duplicate_run") is None and r8["data"]["run_id"] != gray_run_id
    print(f"  ✔ (8) force=true 跳过 duplicate 拦截，创建新 run={r8['data']['run_id'][:12]}")

    s.app_env = "staging"

    # ---- (13) schema 不变 ----
    assert _tables() == tables0, "B2.6 不得新增表/改 schema"
    print("  ✔ (13) 不新增表 / DB schema 不变")

    with open(os.path.join(_SAMPLE_DIR, "b3_alerts_sample.json"), "w", encoding="utf-8") as f:
        json.dump({"b3_alerts": al, "degraded": {k: bs[k] for k in ("degraded_count", "degraded_rate", "degraded_reasons")},
                   "publish_pool": pp}, f, ensure_ascii=False, indent=2)

    _db.engine.dispose()
    if os.path.exists("./_v4p2bb26_test.db"):
        os.remove("./_v4p2bb26_test.db")
    print("\n✅ V4 P2B-B2.6 生产加固 ALL PASSED（13/13 代码项；14/15 为 SOP，见报告）")


if __name__ == "__main__":
    main()
