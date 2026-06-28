"""V4 P2B-B2.1 Visible Layer Variant Differentiation 验证。

覆盖：确定性 signature / 3 条唯一 / 任意两条≥3维(含强可感) / 批次≥5维 / burned=true /
fallback_reason="" / SRT 3/3 / duration∈[25,35] / AAC·playback·PTS / MD5 3/3 / cost=0 /
不写 P2A·P2B-A 表 / 不调火山 / production 403 / ENABLE_P2B_VISIBLE_VARIATION=false 回固定 ASS。

跑法：cd backend && SAMPLE_DIR=/path python tests/verify_v4_p2b_b2_1.py
"""
import json
import os
import subprocess
import sys
import tempfile

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
os.environ["DATABASE_URL"] = "sqlite:///./_v4p2bb21_test.db"

import config
import db as _db

_STORAGE = os.path.join(tempfile.mkdtemp(), "videos")
_SAMPLE_DIR = os.environ.get("SAMPLE_DIR") or os.path.join(tempfile.mkdtemp(), "p2b_b2_1_samples")
_STRONG = {"subtitle_alignment", "cta_style", "highlight_time_bucket"}


def _make_source(path, seconds, w=320, h=240, audio=True):
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=s={w}x{h}:d={seconds}:r=30"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    cmd += ["-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd += [path]
    subprocess.run(cmd, check=True, capture_output=True)


def _client():
    _db.engine.dispose()
    if os.path.exists("./_v4p2bb21_test.db"):
        os.remove("./_v4p2bb21_test.db")
    s = config.settings
    s.auth_required = True; s.jwt_secret = "s"; s.admin_key = "K"
    s.app_env = "staging"; s.enable_compose = False
    s.enable_l2_skills = True; s.enable_p2b_real_execution = True
    s.enable_p2b_visible_layer = True; s.enable_p2b_visible_variation = True
    s.p2b_subtitle_font_path = ""
    s.storage_dir = _STORAGE; s.storage_base_url = "https://test.local/static/videos"
    s.b_remix_target_lo = 25.0; s.b_remix_target_hi = 35.0
    s.b_remix_width = 320; s.b_remix_height = 240; s.b_remix_fps = 30
    from fastapi.testclient import TestClient
    from main import app
    _db.init_db()
    from migrations import p2a_init, p2b_a_init, p2b_b1_init
    p2a_init.run(); p2b_a_init.run(); p2b_b1_init.run()
    return TestClient(app)


def _hdr(t, phone=None):
    from utils import jwt_util
    return {"Authorization": f"Bearer {jwt_util.encode({'tenant_id': t, 'phone': phone or t}, 's')}"}


def _count(table):
    from sqlalchemy import text
    se = _db.SessionLocal()
    try:
        return se.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
    finally:
        se.close()


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
    c = _client()
    A = _hdr("tenantA")

    import httpx
    trig = {"n": 0}
    def _boom(*a, **k):
        trig["n"] += 1
        raise AssertionError("不应触发火山/HTTP")
    httpx.post = httpx.get = _boom

    from b_engine import plan_executor as pe
    from b_engine import qa_checks
    from models import Video

    # ---- 0) 确定性 + 撞档自检（必改2）：同 variant 两次一致；3/6 跨组批次 ≥3 维 ----
    GTO = pe._GROUP_TYPE_ORDER
    specs3 = [{"variant_id": f"var_{i*5+1:02d}", "production_order_id": "po_x",
               "group_type": GTO[i], "group_index": 1} for i in range(3)]
    a1 = pe.resolve_visible_style(specs3[0], specs3[0]["variant_id"])["signature"]
    a2 = pe.resolve_visible_style(specs3[0], specs3[0]["variant_id"])["signature"]
    assert a1 == a2, "确定性失败"
    aud3 = pe.batch_variation_audit(specs3)
    assert aud3["unique"] and aud3["min_pairwise_dims"] >= 3 and aud3["min_pairwise_strong"] >= 1, aud3
    assert aud3["batch_covered_dims"] >= 5 and not aud3["violations"], aud3
    specs6 = [{"variant_id": f"var_{i*5+1:02d}", "production_order_id": "po_x",
               "group_type": GTO[i], "group_index": 1} for i in range(6)]
    aud6 = pe.batch_variation_audit(specs6)
    assert aud6["unique"] and aud6["min_pairwise_dims"] >= 3 and aud6["min_pairwise_strong"] >= 1, aud6
    print(f"  ✔ 确定性 + 撞档自检：3批 min维={aud3['min_pairwise_dims']} 覆盖={aud3['batch_covered_dims']}；"
          f"6批 min维={aud6['min_pairwise_dims']}（均≥3，强可感≥1，唯一）")

    # ---- 前置：P2A + P2B-A confirm + 选 3 条 + 源 ----
    dp = c.post("/api/compose/preview",
                json={"prompt": "达芙荻丽修复精华，痛点皱纹暗沉，产品展示质地，效果对比7天，品牌定格，关注领取试用装",
                      "style": "premium", "ratio": "9:16", "duration": 30, "resolution": "1080p"},
                headers=A).json()["data"]["director_plan_id"]
    po = c.post("/api/production-orders",
                json={"director_plan_id": dp, "scenario": "product_seeding", "platform": "douyin"},
                headers=A).json()["data"]["production_order_id"]
    assert c.post("/api/p2b/execution-plans", json={"production_order_id": po}, headers=A).json()["data"]["total"] == 30
    ep_before, po_before = _count("execution_plans"), _count("production_orders")
    elig = c.get(f"/api/p2b-b/eligible-plans/{po}", headers=A).json()["data"]["items"]
    pick = {}
    for e in elig:
        if e["group_type"] in ("pain_first", "selling_first", "result_close") and e["group_type"] not in pick:
            pick[e["group_type"]] = e["execution_plan_id"]
    plan_ids = [pick["pain_first"], pick["selling_first"], pick["result_close"]]
    src_id = _make_mother("tenantA", 40)

    # ---- 真实执行 3 条 ----
    run = c.post("/api/p2b-b/runs",
                 json={"production_order_id": po, "execution_plan_ids": plan_ids,
                       "source_video_id": src_id, "max_items": 3}, headers=A).json()
    assert run["code"] == 0 and run["data"]["completed"] == 3 and run["data"]["failed"] == 0, run
    run_id = run["data"]["run_id"]
    items = c.get(f"/api/p2b-b/runs/{run_id}/items", headers=A).json()["data"]["items"]
    print("  ✔ 真实执行 3 条成功（completed=3, cost=0）")

    se = _db.SessionLocal()
    sigs, dimsets, md5s = [], [], set()
    for it in items:
        v = se.get(Video, it["video_id"])
        meta = json.loads(v.meta); fb = meta["fallbacks"]
        assert fb["subtitle_burned"] and fb["highlight_burned"] and fb["cta_burned"], fb
        assert fb["fallback_reason"] == "" and fb["variation_applied"] is True, fb
        sig = fb["visible_style_signature"]; sigs.append(sig)
        dims = meta["applied"]["variation_dimensions"]; dimsets.append(dims)
        path = os.path.join(_STORAGE, "viral", f"{v.id}.mp4")
        ok, _ = qa_checks.playback_validate(path); assert ok
        pok, _ = qa_checks.pts_check(path); assert pok
        dur = qa_checks.probe_duration(path); assert 24.5 <= dur <= 35.5, dur
        assert qa_checks.has_audio(path)
        md5s.add(it["md5"])
        import shutil
        shutil.copy(path, os.path.join(_SAMPLE_DIR, f"{it['group_type']}_{v.id}.mp4"))
    se.close()

    # ---- signature 唯一 + 任意两条≥3维(含强) + 批次≥5维 ----
    assert len(set(sigs)) == 3, f"signature 不唯一: {sigs}"
    import itertools
    dk = list(dimsets[0].keys())
    for (i, d1), (j, d2) in itertools.combinations(enumerate(dimsets), 2):
        diff = [k for k in dk if d1[k] != d2[k]]
        strong = [k for k in diff if k in _STRONG]
        assert len(diff) >= 3 and len(strong) >= 1, f"{i}vs{j} diff={diff}"
    covered = [k for k in dk if len({d[k] for d in dimsets}) > 1]
    assert len(covered) >= 5, f"批次覆盖维度 {covered}"
    print(f"  ✔ 3 条 signature 3/3 唯一；任意两条≥3维(含强可感≥1)；批次覆盖 {len(covered)} 维(≥5)")

    # ---- burned + MD5 + 底座 ----
    assert len(md5s) == 3, f"MD5 {len(md5s)}/3"
    print("  ✔ 字幕/高光卡/CTA burned=true / duration∈[25,35] / AAC / playback / PTS / MD5 3-3 唯一")

    # ---- 不写 P2A/P2B-A 表 + cost=0 + 不调火山 ----
    assert _count("execution_plans") == ep_before and _count("production_orders") == po_before
    from sqlalchemy import text
    se = _db.SessionLocal()
    amt = se.execute(text("SELECT COALESCE(SUM(amount),0) FROM cost_records WHERE api_name='video.p2b_b1'")).scalar()
    se.close()
    assert (amt or 0) == 0 and trig["n"] == 0
    print("  ✔ 不写 P2A/P2B-A 表 / cost=0 / 不调火山")

    # ---- 确定性复跑：同 variant 再执行一次 → signature 一致 ----
    run2 = c.post("/api/p2b-b/runs",
                  json={"production_order_id": po, "execution_plan_ids": [plan_ids[0]],
                        "source_video_id": src_id, "max_items": 1}, headers=A).json()
    it2 = c.get(f"/api/p2b-b/runs/{run2['data']['run_id']}/items", headers=A).json()["data"]["items"][0]
    se = _db.SessionLocal()
    sig2 = json.loads(se.get(Video, it2["video_id"]).meta)["fallbacks"]["visible_style_signature"]
    se.close()
    assert sig2 == sigs[0], f"同 variant 复跑 signature 不一致 {sig2} vs {sigs[0]}"
    print("  ✔ 确定性复跑：同 variant 再生成 signature 一致")

    # ---- production 403 不退化 ----
    config.settings.app_env = "production"
    assert c.post("/api/p2b-b/runs", json={"production_order_id": po, "execution_plan_ids": plan_ids,
                  "source_video_id": src_id, "max_items": 3}, headers=A).status_code == 403
    config.settings.app_env = "staging"
    print("  ✔ production 403 不退化")

    # ======== 单元级：SRT / ENABLE_P2B_VISIBLE_VARIATION=false 回固定 ASS ========
    src_path = os.path.join(_STORAGE, "mother", f"{src_id}.mp4")
    src_dur = qa_checks.probe_duration(src_path); audio = qa_checks.has_audio(src_path)
    se = _db.SessionLocal()
    row = se.execute(text("SELECT variant_plan_json, variant_id FROM execution_plans LIMIT 1")).fetchone()
    se.close()
    vpj, vid_ = row[0], row[1]
    W, H, FPS, lo, hi, tol = 320, 240, 30, 25.0, 35.0, 0.5
    d = tempfile.mkdtemp()

    # SRT sidecar 3/3：对 3 条直接执行确认 srt 存在
    for k, pid in enumerate(plan_ids):
        se = _db.SessionLocal()
        r = se.execute(text("SELECT variant_plan_json, variant_id FROM execution_plans WHERE execution_plan_id=:i"),
                       {"i": pid}).fetchone()
        se.close()
        o = os.path.join(d, f"srt_{k}.mp4")
        res = pe.execute_plan(src_path, src_dur, audio, o, r[0], W, H, FPS, lo, hi, tol, set(), variant_id=r[1])
        assert os.path.exists(os.path.splitext(o)[0] + ".srt"), f"SRT {k} 缺失"
        assert res["fallbacks"]["variation_applied"] is True
    print("  ✔ SRT sidecar 3/3 存在（烧录成功也输出）")

    # variation=false → 回固定 ASS（signature=fixed，仍 burned，仍可见）
    config.settings.enable_p2b_visible_variation = False
    o2 = os.path.join(d, "fixed.mp4")
    rf = pe.execute_plan(src_path, src_dur, audio, o2, vpj, W, H, FPS, lo, hi, tol, set(), variant_id=vid_)
    config.settings.enable_p2b_visible_variation = True
    assert rf["fallbacks"]["visible_style_signature"] == "fixed", rf["fallbacks"]
    assert rf["fallbacks"]["variation_applied"] is False
    assert rf["fallbacks"]["subtitle_burned"] and rf["fallbacks"]["cta_burned"], rf["fallbacks"]
    assert rf["fallbacks"]["fallback_reason"] == "" and rf["ok"]
    print("  ✔ ENABLE_P2B_VISIBLE_VARIATION=false → 回 B2 固定 ASS（signature=fixed，可见层不丢）")

    print(f"\n  样片目录：{_SAMPLE_DIR}")
    for f in sorted(os.listdir(_SAMPLE_DIR)):
        if f.endswith(".mp4"):
            print(f"    {f}")

    _db.engine.dispose()
    if os.path.exists("./_v4p2bb21_test.db"):
        os.remove("./_v4p2bb21_test.db")
    print("\n✅ V4 P2B-B2.1 ALL PASSED")


if __name__ == "__main__":
    main()
