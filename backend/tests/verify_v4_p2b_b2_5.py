"""V4 P2B-B2.5 音频/编码合规差异化 验证。

覆盖：响度规范化(-14 LUFS±容差)/True Peak/EQ 逐 variant 确定性/audio_encoding_signature 确定性+唯一/
metadata 清理+诚实 provenance/无伪造 make·model·GPS/ENABLE_P2B_AUDIO_ENCODING_DIFF=false 回 B2.1/
3 条成片·duration·AAC·playback·PTS·MD5·cost=0/不写 P2A·P2B-A 表/不调火山/production 403。

跑法：cd backend && SAMPLE_DIR=/path python tests/verify_v4_p2b_b2_5.py
"""
import json
import os
import re
import subprocess
import sys
import tempfile

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
os.environ["DATABASE_URL"] = "sqlite:///./_v4p2bb25_test.db"

import config
import db as _db

_STORAGE = os.path.join(tempfile.mkdtemp(), "videos")
_SAMPLE_DIR = os.environ.get("SAMPLE_DIR") or os.path.join(tempfile.mkdtemp(), "p2b_b2_5_samples")


def _make_source(path, seconds, w=320, h=240, audio=True):
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=s={w}x{h}:d={seconds}:r=30"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    cmd += ["-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd += [path]
    subprocess.run(cmd, check=True, capture_output=True)


def _measure_loudness(path):
    """ebur128 测 Integrated loudness(I) 与 True Peak。返回 (I_lufs, true_peak_dbfs)。"""
    r = subprocess.run(["ffmpeg", "-i", path, "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True)
    log = r.stderr
    # 取 Summary 段最后出现的 I 与 Peak
    i_vals = re.findall(r"I:\s*(-?\d+\.?\d*)\s*LUFS", log)
    pk_vals = re.findall(r"Peak:\s*(-?\d+\.?\d*)\s*dBFS", log)
    I = float(i_vals[-1]) if i_vals else None
    TP = float(pk_vals[-1]) if pk_vals else None
    return I, TP


def _format_tags(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags",
                        "-of", "json", path], capture_output=True, text=True)
    try:
        return json.loads(r.stdout).get("format", {}).get("tags", {})
    except (ValueError, KeyError):
        return {}


def _client():
    _db.engine.dispose()
    if os.path.exists("./_v4p2bb25_test.db"):
        os.remove("./_v4p2bb25_test.db")
    s = config.settings
    s.auth_required = True; s.jwt_secret = "s"; s.admin_key = "K"
    s.app_env = "staging"; s.enable_compose = False
    s.enable_l2_skills = True; s.enable_p2b_real_execution = True
    s.enable_p2b_visible_layer = True; s.enable_p2b_visible_variation = True
    s.enable_p2b_audio_encoding_diff = True
    s.p2b_loudness_target_lufs = -14.0; s.p2b_true_peak_dbtp = -1.0
    s.p2b_build_commit = "testcommit"
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

    # ---- 0) audio_encoding_info：确定性 + EQ 逐 variant + signature 跨 run 一致 ----
    i1 = pe.audio_encoding_info("var_01", run_id="runA")
    i2 = pe.audio_encoding_info("var_01", run_id="runB")   # 不同 run → signature 仍一致（不含 run_id）
    assert i1["audio_encoding_signature"] == i2["audio_encoding_signature"], "signature 应跨 run 一致"
    assert i1["provenance"] != i2["provenance"], "provenance 应含 run_id 而不同"
    assert i1["target_lufs"] == -14.0 and i1["true_peak_target_dbtp"] == -1.0
    assert i1["metadata_cleaned"] is True and i1["tempo_factor"] == 1.0
    eqs = {pe.audio_encoding_info(f"var_{n:02d}")["eq_profile"] for n in range(1, 13)}
    assert len(eqs) >= 2, f"EQ profile 应按 variant 分布: {eqs}"
    print(f"  ✔ audio_encoding_info：确定性、signature 跨 run 一致、EQ 逐 variant（{len(eqs)} 种 profile）")

    # ---- 前置：P2A + P2B-A confirm + 选 3 + 源 ----
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
    assert run["code"] == 0 and run["data"]["completed"] == 3, run
    run_id = run["data"]["run_id"]
    items = c.get(f"/api/p2b-b/runs/{run_id}/items", headers=A).json()["data"]["items"]
    print("  ✔ 真实执行 3 条成功（completed=3, cost=0）")

    se = _db.SessionLocal()
    sigs, md5s, lufs_list = [], set(), []
    for it in items:
        v = se.get(Video, it["video_id"])
        meta = json.loads(v.meta); ae = meta["audio_encoding"]
        assert ae["applied"] is True and ae["metadata_cleaned"] is True, ae
        assert ae["target_lufs"] == -14.0 and ae["tempo_factor"] == 1.0, ae
        assert "generated_by=meiye_v4_p2b" in ae["provenance"] and "ai_generated=true" in ae["provenance"]
        assert f"run_id={run_id}" in ae["provenance"], ae["provenance"]
        sigs.append(ae["audio_encoding_signature"])
        path = os.path.join(_STORAGE, "viral", f"{v.id}.mp4")
        # 底座
        ok, _ = qa_checks.playback_validate(path); assert ok
        pok, _ = qa_checks.pts_check(path); assert pok
        dur = qa_checks.probe_duration(path); assert 24.5 <= dur <= 35.5, dur
        assert qa_checks.has_audio(path)
        md5s.add(it["md5"])
        # 响度 + True Peak
        I, TP = _measure_loudness(path)
        lufs_list.append((it["group_type"], I, TP))
        assert I is not None and abs(I - (-14.0)) <= 1.5, f"{it['group_type']} I={I} 偏离 -14 过大"
        assert TP is not None and TP <= -0.5, f"{it['group_type']} TruePeak={TP} 超限"
        # AAC 44100 stereo
        astream = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a",
                                  "-show_entries", "stream=codec_name,sample_rate,channels",
                                  "-of", "json", path], capture_output=True, text=True)
        ai = json.loads(astream.stdout)["streams"][0]
        assert ai["codec_name"] == "aac" and ai["sample_rate"] == "44100" and ai["channels"] == 2, ai
        # metadata：comment 含 provenance；无伪造 make/model/GPS
        tags = {k.lower(): val for k, val in _format_tags(path).items()}
        assert "generated_by=meiye_v4_p2b" in tags.get("comment", ""), tags
        for bad in ("make", "model", "location", "com.apple.quicktime.make",
                    "com.apple.quicktime.model", "com.apple.quicktime.location.iso6709"):
            assert bad not in tags, f"不应存在伪造标签 {bad}: {tags}"
        import shutil
        shutil.copy(path, os.path.join(_SAMPLE_DIR, f"{it['group_type']}_{v.id}.mp4"))
    se.close()
    assert len(md5s) == 3, f"MD5 {len(md5s)}/3"
    assert len(set(sigs)) == 3, f"audio_encoding_signature 应 3/3 唯一: {sigs}"
    print("  ✔ 响度≈-14 LUFS(±1.5) / TruePeak≤-0.5 / AAC44100stereo / metadata 清理+诚实溯源 / 无伪造标签")
    print(f"    实测响度: " + "; ".join(f"{g}:{I}LUFS,TP{TP}" for g, I, TP in lufs_list))
    print("  ✔ audio_encoding_signature 3/3 唯一 / MD5 3/3 唯一 / duration∈[25,35]")

    # ---- run_items.qa_json.audio_encoding ----
    from sqlalchemy import text
    se = _db.SessionLocal()
    qj = se.execute(text("SELECT qa_json FROM p2b_execution_run_items WHERE run_id=:r LIMIT 1"),
                    {"r": run_id}).fetchone()
    se.close()
    assert qj and "audio_encoding" in json.loads(qj[0]), "run_items.qa_json 应含 audio_encoding"
    print("  ✔ run_items.qa_json.audio_encoding + videos.meta.audio_encoding 已记录（零新增表）")

    # ---- 不写 P2A/P2B-A 表 + cost=0 + 不调火山 ----
    assert _count("execution_plans") == ep_before and _count("production_orders") == po_before
    se = _db.SessionLocal()
    amt = se.execute(text("SELECT COALESCE(SUM(amount),0) FROM cost_records WHERE api_name='video.p2b_b1'")).scalar()
    se.close()
    assert (amt or 0) == 0 and trig["n"] == 0
    print("  ✔ 不写 P2A/P2B-A 表 / cost=0 / 不调火山")

    # ---- production 403 不退化 ----
    config.settings.app_env = "production"
    assert c.post("/api/p2b-b/runs", json={"production_order_id": po, "execution_plan_ids": plan_ids,
                  "source_video_id": src_id, "max_items": 3}, headers=A).status_code == 403
    config.settings.app_env = "staging"
    print("  ✔ production 403 不退化")

    # ---- ENABLE_P2B_AUDIO_ENCODING_DIFF=false → 回 B2.1 口径（无 loudnorm、无 provenance comment）----
    src_path = os.path.join(_STORAGE, "mother", f"{src_id}.mp4")
    sd = qa_checks.probe_duration(src_path); au = qa_checks.has_audio(src_path)
    se = _db.SessionLocal()
    row = se.execute(text("SELECT variant_plan_json, variant_id FROM execution_plans LIMIT 1")).fetchone()
    se.close()
    config.settings.enable_p2b_audio_encoding_diff = False
    d = tempfile.mkdtemp(); o = os.path.join(d, "off.mp4")
    rf = pe.execute_plan(src_path, sd, au, o, row[0], 320, 240, 30, 25.0, 35.0, 0.5, set(),
                         variant_id=row[1], run_id="x")
    config.settings.enable_p2b_audio_encoding_diff = True
    assert rf["audio_encoding"]["applied"] is False, rf["audio_encoding"]
    tags_off = {k.lower(): v for k, v in _format_tags(o).items()}
    assert "generated_by=meiye_v4_p2b" not in tags_off.get("comment", ""), "关闭后不应写 provenance"
    assert rf["ok"], "关闭后底座仍成片"
    print("  ✔ ENABLE_P2B_AUDIO_ENCODING_DIFF=false → 回 B2.1 口径（无 loudnorm/provenance，底座不退化）")

    print(f"\n  样片目录：{_SAMPLE_DIR}")
    for f in sorted(os.listdir(_SAMPLE_DIR)):
        if f.endswith(".mp4"):
            print(f"    {f}")

    _db.engine.dispose()
    if os.path.exists("./_v4p2bb25_test.db"):
        os.remove("./_v4p2bb25_test.db")
    print("\n✅ V4 P2B-B2.5 ALL PASSED")


if __name__ == "__main__":
    main()
