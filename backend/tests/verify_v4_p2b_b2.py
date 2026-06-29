"""V4 P2B-B2 Visible Layer 验证：subtitle / highlight_card / CTA 稳定可见 + 分层 fallback。

覆盖：font resolver / runs/preview 返回 visible_layer_ready / 3 条成片 / 可见层烧录 /
SRT sidecar / 分层 fallback（full→subtitle_only→none / no_font / disabled）/ fallbacks 记录 /
底座不退化（duration/AAC/playback/PTS/MD5/cost）/ 不写 P2A·P2B-A 表 / 双闸门 / 不调火山。

跑法：cd backend && SAMPLE_DIR=/path python tests/verify_v4_p2b_b2.py
"""
import json
import os
import subprocess
import sys
import tempfile

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
os.environ["DATABASE_URL"] = "sqlite:///./_v4p2bb2_test.db"

import config
import db as _db

_STORAGE = os.path.join(tempfile.mkdtemp(), "videos")
_SAMPLE_DIR = os.environ.get("SAMPLE_DIR") or os.path.join(tempfile.mkdtemp(), "p2b_b2_samples")


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
    if os.path.exists("./_v4p2bb2_test.db"):
        os.remove("./_v4p2bb2_test.db")
    s = config.settings
    s.auth_required = True; s.jwt_secret = "s"; s.admin_key = "K"
    s.app_env = "staging"; s.enable_compose = False
    s.enable_l2_skills = True
    s.enable_p2b_real_execution = True
    s.enable_p2b_visible_layer = True
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
        raise AssertionError("P2B-B2 不应触发火山/HTTP（fc-match 用 subprocess 非 httpx）")
    httpx.post = httpx.get = _boom

    from b_engine import plan_executor as pe
    from b_engine import qa_checks
    from models import Video

    # ---- 1) font resolver 命中字体 ----
    fh = pe.resolve_font()
    assert fh["available"] and fh["font_path"] and os.path.exists(fh["font_path"]), fh
    assert fh["source"] in ("settings", "candidate", "fc-match"), fh
    print(f"  ✔ font resolver 命中：{fh['source']} → {fh['font_path']}")

    # ---- 前置：P2A 生产单 + P2B-A confirm 30 ----
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
    print("  ✔ 前置：P2A 生产单 + 30 条 confirm + 选 3 条 + 源(40s)")

    # ---- 2) runs/preview 返回 visible_layer_ready ----
    pv = c.post("/api/p2b-b/runs/preview",
                json={"production_order_id": po, "execution_plan_ids": plan_ids,
                      "source_video_id": src_id, "max_items": 3}, headers=A).json()
    assert pv["code"] == 0, pv
    assert pv["data"]["visible_layer_ready"] is True, pv["data"]
    assert pv["data"]["visible_layer"]["font_available"] is True, pv["data"]["visible_layer"]
    print("  ✔ runs/preview 返回 visible_layer_ready=true + font 信息")

    # ---- 3) 真实执行 3 条（可见层开）----
    run = c.post("/api/p2b-b/runs",
                 json={"production_order_id": po, "execution_plan_ids": plan_ids,
                       "source_video_id": src_id, "max_items": 3}, headers=A).json()
    assert run["code"] == 0 and run["data"]["completed"] == 3 and run["data"]["failed"] == 0, run
    run_id = run["data"]["run_id"]
    items = c.get(f"/api/p2b-b/runs/{run_id}/items", headers=A).json()["data"]["items"]
    assert len(items) == 3, items
    print("  ✔ 真实执行 3 条成功（completed=3, cost=0）")

    # ---- 4) 可见层烧录 + fallbacks 记录 + 底座不退化 + 样片落盘 ----
    se = _db.SessionLocal()
    md5s = set()
    for it in items:
        v = se.get(Video, it["video_id"])
        meta = json.loads(v.meta)
        fb = meta["fallbacks"]
        # 字体存在 → 应烧录（full tier 成功）
        assert fb["subtitle_burned"] is True, fb
        assert fb["highlight_burned"] is True, fb
        assert fb["cta_burned"] is True, fb
        assert fb["font_path"] and fb["font_source"] in ("settings", "candidate", "fc-match"), fb
        assert fb["fallback_reason"] == "", fb
        # applied 记录
        assert it["subtitle_applied"] and it["cta_applied"], it
        # 底座
        path = os.path.join(_STORAGE, "viral", f"{v.id}.mp4")
        ok, _ = qa_checks.playback_validate(path); assert ok
        pok, _ = qa_checks.pts_check(path); assert pok
        dur = qa_checks.probe_duration(path); assert 24.5 <= dur <= 35.5, dur
        assert qa_checks.has_audio(path)
        md5s.add(it["md5"])
        import shutil
        shutil.copy(path, os.path.join(_SAMPLE_DIR, f"{it['group_type']}_{v.id}.mp4"))
    se.close()
    assert len(md5s) == 3, f"MD5 {len(md5s)}/3"
    print("  ✔ 3 条：字幕/高光卡/CTA 均烧录(burned=true) / fallback_reason='' / duration∈[25,35] / MD5 3-3 唯一")

    # ---- 5) 不写 P2A/P2B-A 表 + cost=0 + 不调火山 ----
    assert _count("execution_plans") == ep_before and _count("production_orders") == po_before
    from sqlalchemy import text
    se = _db.SessionLocal()
    amt = se.execute(text("SELECT COALESCE(SUM(amount),0) FROM cost_records WHERE api_name='video.p2b_b1'")).scalar()
    se.close()
    assert (amt or 0) == 0 and trig["n"] == 0
    print("  ✔ 不写 P2A/P2B-A 表 / cost=0 / 不调火山")

    # ---- 6) 双闸门不退化（flag=false→4031；production→403）----
    config.settings.enable_p2b_real_execution = False
    assert c.post("/api/p2b-b/runs", json={"production_order_id": po, "execution_plan_ids": plan_ids,
                  "source_video_id": src_id, "max_items": 3}, headers=A).json()["code"] == 4031
    config.settings.enable_p2b_real_execution = True
    config.settings.app_env = "production"
    assert c.post("/api/p2b-b/runs", json={"production_order_id": po, "execution_plan_ids": plan_ids,
                  "source_video_id": src_id, "max_items": 3}, headers=A).status_code == 403
    config.settings.app_env = "staging"
    print("  ✔ 双闸门不退化（flag=false→4031；production→403）")

    # ======== 单元级：SRT / no_font / 分层降级 / disabled ========
    src_path = os.path.join(_STORAGE, "mother", f"{src_id}.mp4")
    src_dur = qa_checks.probe_duration(src_path)
    audio = qa_checks.has_audio(src_path)
    se = _db.SessionLocal()
    sample_ep = se.execute(text("SELECT variant_plan_json, variant_id FROM execution_plans LIMIT 1")).fetchone()
    se.close()
    vpj, vid_ = sample_ep[0], sample_ep[1]
    W, H, FPS = 320, 240, 30
    lo, hi, tol = 25.0, 35.0, 0.5

    # SRT sidecar 永远输出（烧录成功也输出）
    d = tempfile.mkdtemp()
    out = os.path.join(d, "u1.mp4")
    res = pe.execute_plan(src_path, src_dur, audio, out, vpj, W, H, FPS, lo, hi, tol, set(), variant_id=vid_)
    assert os.path.exists(os.path.splitext(out)[0] + ".srt"), "SRT sidecar 应存在"
    assert res["fallbacks"]["srt"] is True and res["fallbacks"]["subtitle_burned"] is True
    print("  ✔ SRT sidecar 永远输出（烧录成功也输出）")

    # no_font：monkeypatch resolve_font → 不可用 → fallback_reason=no_font，底座仍成片
    orig_resolve = pe.resolve_font
    pe.resolve_font = lambda: {"available": False, "font_path": None, "source": "none"}
    try:
        out2 = os.path.join(d, "u2.mp4")
        r2 = pe.execute_plan(src_path, src_dur, audio, out2, vpj, W, H, FPS, lo, hi, tol, set(), variant_id=vid_)
    finally:
        pe.resolve_font = orig_resolve
    assert r2["fallbacks"]["fallback_reason"] == "no_font", r2["fallbacks"]
    assert r2["fallbacks"]["subtitle_burned"] is False and os.path.exists(out2) and r2["ok"]
    assert os.path.exists(os.path.splitext(out2)[0] + ".srt")
    print("  ✔ no_font 降级：fallback_reason=no_font，底座仍成片 + SRT")

    # 分层降级（B2.1 后链路：差异化 ASS → B2 固定 ASS → 无叠加；不再有 subtitle_only/drawtext）
    orig_render = pe._render
    calls = {"n": 0}
    def _render_fail_full(src, o, plan, au, w, h, f, overlays, visual_filter=""):
        calls["n"] += 1
        # 第一次（差异化 ASS）强制失败 → 降到固定 ASS（仍渲染三层），其余正常
        if calls["n"] == 1:
            raise subprocess.CalledProcessError(1, ["ffmpeg"])
        return orig_render(src, o, plan, au, w, h, f, overlays, visual_filter)
    pe._render = _render_fail_full
    try:
        out3 = os.path.join(d, "u3.mp4")
        r3 = pe.execute_plan(src_path, src_dur, audio, out3, vpj, W, H, FPS, lo, hi, tol, set(), variant_id=vid_)
    finally:
        pe._render = orig_render
    assert r3["fallbacks"]["fallback_reason"] == "degraded_to_fixed_ass", r3["fallbacks"]
    assert r3["fallbacks"]["variation_applied"] is False and r3["fallbacks"]["variation_degraded"] is True
    assert r3["fallbacks"]["subtitle_burned"] and r3["fallbacks"]["cta_burned"], r3["fallbacks"]
    assert r3["ok"], "降级后仍应成片"
    print("  ✔ 分层降级：差异化 ASS 失败 → degraded_to_fixed_ass（B2 固定 ASS 三层仍烧录，底座不退化）")

    # disabled：关可见层 → fallback_reason=visible_layer_disabled
    config.settings.enable_p2b_visible_layer = False
    out4 = os.path.join(d, "u4.mp4")
    r4 = pe.execute_plan(src_path, src_dur, audio, out4, vpj, W, H, FPS, lo, hi, tol, set(), variant_id=vid_)
    config.settings.enable_p2b_visible_layer = True
    assert r4["fallbacks"]["fallback_reason"] == "visible_layer_disabled", r4["fallbacks"]
    assert r4["fallbacks"]["subtitle_burned"] is False and r4["ok"]
    print("  ✔ ENABLE_P2B_VISIBLE_LAYER=false → 回纯底座（visible_layer_disabled）")

    print(f"\n  样片目录：{_SAMPLE_DIR}")
    for f in sorted(os.listdir(_SAMPLE_DIR)):
        if f.endswith(".mp4"):
            print(f"    {f}")

    _db.engine.dispose()
    if os.path.exists("./_v4p2bb2_test.db"):
        os.remove("./_v4p2bb2_test.db")
    print("\n✅ V4 P2B-B2 ALL PASSED")


if __name__ == "__main__":
    main()
