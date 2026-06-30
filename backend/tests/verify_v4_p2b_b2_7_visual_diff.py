"""V4 P2B-B2.7 视觉合规差异化层 验证（逐 variant 构图 + 轻调色；注入 _norm 之后、ASS 叠加之前）。

覆盖 17 项：flag=false 字节等价 / flag=true visual_profile 存在 / signature 3 唯一 / 参数不超上限 /
无 hue / 无 mirror / 无变速 / 音频路径零改 / 不新增表 / 不改 schema / 路由契约不变 /
可见层仍叠加在构图之后 / meta.visual_encoding 写入 / B3 可评估视觉差异(off<on) / B2.5 音频不退化 /
production 403 / rollback 关 flag 回 078fcfe 行为。

跑法：cd backend && SAMPLE_DIR=/path python tests/verify_v4_p2b_b2_7_visual_diff.py
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
os.environ["DATABASE_URL"] = "sqlite:///./_v4p2bb27_test.db"

import config
import db as _db

_STORAGE = os.path.join(tempfile.mkdtemp(), "videos")
_SAMPLE_DIR = os.environ.get("SAMPLE_DIR") or os.path.join(tempfile.mkdtemp(), "p2b_b27_samples")
_LIMITS = {"zoom_max": 1.12, "contrast": (0.92, 1.10), "saturation": (0.92, 1.12),
           "gamma": (0.92, 1.08), "brightness_abs": 0.04}
_FORBIDDEN = ("hue=", "hflip", "vflip", "transpose", "atempo")


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


def _measure_loudness(path):
    r = subprocess.run(["ffmpeg", "-i", path, "-map", "0:a", "-af",
                        "loudnorm=I=-14:TP=-1:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)
    if not m:
        return None, None
    try:
        d = json.loads(m[-1]); return float(d["input_i"]), float(d["input_tp"])
    except (ValueError, KeyError):
        return None, None


def _client(visual_diff):
    _db.engine.dispose()
    if os.path.exists("./_v4p2bb27_test.db"):
        os.remove("./_v4p2bb27_test.db")
    s = config.settings
    s.auth_required = True; s.jwt_secret = "s"; s.admin_key = "K"
    s.app_env = "staging"; s.enable_compose = False
    s.enable_l2_skills = True; s.enable_p2b_real_execution = True
    s.enable_p2b_visible_layer = True; s.enable_p2b_visible_variation = True
    s.enable_p2b_audio_encoding_diff = True; s.enable_p2b_b3_score = True
    s.enable_p2b_visual_diff = visual_diff
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


def _run_batch(c, A):
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
    run = c.post("/api/p2b-b/runs",
                 json={"production_order_id": po, "execution_plan_ids": plan_ids,
                       "source_video_id": src_id, "max_items": 3}, headers=A).json()
    assert run["code"] == 0 and run["data"]["completed"] == 3, run
    return po, run["data"]["run_id"], plan_ids, elig


def _b3_visual_mean(c, A, run_id):
    data = c.post("/api/p2b-b3/score", json={"run_id": run_id}, headers=A).json()["data"]
    vds = [cell["visual_distance"] for cell in data["pairwise_matrix"]]
    return sum(vds) / len(vds), data


def main():
    os.makedirs(_SAMPLE_DIR, exist_ok=True)
    from b_engine import plan_executor as pe

    # ---- (1) flag=false：_build_cmd 视频 trim 段与未引入 B2.7 字节等价 ----
    plan = {"windows": [{"role": "产品", "start": 1.0, "end": 4.0, "seg": 3.0},
                        {"role": "品牌", "start": 5.0, "end": 7.0, "seg": 2.0}],
            "transitions": [{"xfade": "fade", "duration": 0.5, "from_role": "产品", "to_role": "品牌"}],
            "target_output": 30.0, "n": 2}
    cmd_off = pe._build_cmd("s.mp4", "o.mp4", plan, True, 1080, 1920, 30, [], "")
    fc_off = cmd_off[cmd_off.index("-filter_complex") + 1]
    norm = pe._norm(1080, 1920, 30)
    exp0 = f"[0:v]trim=start=1.000:end=4.000,{norm}[v0]"
    exp1 = f"[0:v]trim=start=5.000:end=7.000,{norm}[v1]"
    assert exp0 in fc_off and exp1 in fc_off, "flag=false 时 _norm 段必须与旧格式字节等价"
    assert ",scale=iw*" not in fc_off and "eq=contrast" not in fc_off, "flag=false 不应注入任何视觉滤镜"
    print("  ✔ (1) flag=false：_build_cmd/_norm 与 078fcfe 字节等价（无视觉滤镜注入）")

    # ---- (5/6/7) flag=true：滤镜串无 hue/mirror/变速 + (4) 参数不超上限 ----
    config.settings.enable_p2b_visual_diff = True
    sigs, profiles = [], []
    for gt, vid in [("pain_first", "va"), ("selling_first", "vb"), ("result_close", "vc")]:
        info = pe.visual_profile_info(vid, {"group_type": gt, "group_index": 1, "production_order_id": "po"}, 1080, 1920)
        assert info["applied"] is True
        sigs.append(info["visual_profile_signature"]); profiles.append(info)
        vf = info["visual_filter"]
        for bad in _FORBIDDEN:
            assert bad not in vf, f"禁用滤镜 {bad} 出现在 {vf}"
        p = info["profile"]
        assert 1.0 <= p["zoom"] <= _LIMITS["zoom_max"], p
        assert _LIMITS["contrast"][0] <= p["contrast"] <= _LIMITS["contrast"][1], p
        assert _LIMITS["saturation"][0] <= p["saturation"] <= _LIMITS["saturation"][1], p
        assert _LIMITS["gamma"][0] <= p["gamma"] <= _LIMITS["gamma"][1], p
        assert abs(p["brightness"]) <= _LIMITS["brightness_abs"], p
        assert p["sharpness"] is False, "锐度第一版必须 OFF"
        assert 0.42 <= p["pan_x"] <= 0.58, p   # 中心 ±8%
    # (3) signature 3 唯一
    assert len(set(sigs)) == 3, f"visual_profile_signature 应 3 唯一: {sigs}"
    print(f"  ✔ (3) signature 3 唯一 / (4) 参数≤上限 / (5)无hue (6)无mirror (7)无变速  sigs={sigs}")

    # ---- (12) 可见层叠加在视觉处理之后：视觉滤镜出现在 [vk] 段，overlay 在其后 ----
    ov = ["subtitles=/tmp/x.ass"]
    info_b = pe.visual_profile_info("vb", {"group_type": "selling_first", "group_index": 1}, 320, 240)
    cmd_on = pe._build_cmd("s.mp4", "o.mp4", plan, True, 320, 240, 30, ov, info_b["visual_filter"])
    fc_on = cmd_on[cmd_on.index("-filter_complex") + 1]
    assert info_b["visual_filter"].split(",")[0] in fc_on, "视觉滤镜应注入 _norm 段"
    # 视觉滤镜在 [v0]/[v1] 内（叠加前）；subtitles overlay 在拼接之后
    assert fc_on.index("eq=contrast") < fc_on.index("subtitles="), "视觉滤镜必须在 ASS 叠加之前"
    print("  ✔ (12) 视觉处理在 _norm 段（ASS 叠加之前）→ 字幕/高光/CTA 不被裁、品牌色不被调色")

    # ---- 真实跑：先 OFF 基线（B3 视觉差异），再 ON ----
    c = _client(visual_diff=False)
    A = _hdr("tenantA")
    tables0 = _tables()
    po0, run_off, _, _ = _run_batch(c, A)
    vmean_off, _ = _b3_visual_mean(c, A, run_off)
    # off 时 meta.visual_encoding.applied=False
    from models import Video
    se = _db.SessionLocal()
    any_v = se.query(Video).filter(Video.type == "viral").first()
    meta_off = json.loads(any_v.meta)
    se.close()
    assert meta_off.get("visual_encoding", {}).get("applied") is False, meta_off.get("visual_encoding")
    print(f"  ✔ (17/rollback) flag=false 真实跑：meta.visual_encoding.applied=False（078fcfe 行为）vmean_off={vmean_off:.4f}")

    # ON
    c = _client(visual_diff=True)
    A = _hdr("tenantA")
    po1, run_on, plan_ids_on, elig_on = _run_batch(c, A)
    vmean_on, b3data = _b3_visual_mean(c, A, run_on)

    items = c.get(f"/api/p2b-b/runs/{run_on}/items", headers=A).json()["data"]["items"]
    vids = sorted(it["video_id"] for it in items)
    se = _db.SessionLocal()
    vis_sigs, zooms = [], []
    for vid in vids:
        v = se.get(Video, vid)
        meta = json.loads(v.meta)
        ve = meta.get("visual_encoding", {})
        # (2) visual_profile 存在 + (13) meta.visual_encoding 写入
        assert ve.get("applied") is True, ve
        assert "visual_profile_signature" in ve and ve["profile"], ve
        vis_sigs.append(ve["visual_profile_signature"])
        zooms.append(ve["profile"]["zoom"])
        p = ve["profile"]
        assert p["zoom"] <= _LIMITS["zoom_max"] and p["sharpness"] is False
        path = os.path.join(_STORAGE, "viral", f"{vid}.mp4")
        # (15) B2.5 音频不退化
        I, TP = _measure_loudness(path)
        assert I is not None and -15.0 <= I <= -13.0, f"B2.5 退化 I={I}"
        assert TP is not None and TP <= -1.0, f"B2.5 退化 TP={TP}"
        # (8) 音频路径零改：AAC 44100 stereo + B2.5 applied
        ai = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a",
              "-show_entries", "stream=codec_name,sample_rate,channels", "-of", "json", path],
              capture_output=True, text=True).stdout)["streams"][0]
        assert ai["codec_name"] == "aac" and ai["sample_rate"] == "44100" and ai["channels"] == 2, ai
        assert meta.get("audio_encoding", {}).get("applied") is True
    se.close()
    assert len(set(vis_sigs)) == 3, f"3 条 visual_profile_signature 应唯一: {vis_sigs}"
    print(f"  ✔ (2) visual_profile 存在 / (13) meta.visual_encoding 写入 / (8) 音频路径零改 / (15) B2.5 不退化")

    # ---- (HOTFIX-1) zoom 档位生效：3 条至少覆盖 2 个 zoom 档位（ECS 失败时全 1.0）----
    assert len(set(zooms)) >= 2, f"3 条必须至少覆盖 2 个 zoom 档位（修复前全 1.0）: {zooms}"
    assert set(zooms) == {1.00, 1.06, 1.12}, f"跨组 3 条应覆盖 1.00/1.06/1.12: {zooms}"
    assert all(z <= 1.12 for z in zooms), zooms
    # var_01/02/03 也须至少 2 档（variant_index 驱动 zoom）
    vz = [pe.resolve_visual_profile({"group_type": gt, "group_index": 1}, vid)["zoom"]
          for gt, vid in [("pain_first", "var_01"), ("selling_first", "var_02"), ("result_close", "var_03")]]
    assert len(set(vz)) >= 2, f"var_01/02/03 应至少 2 个 zoom 档位: {vz}"
    print(f"  ✔ (HOTFIX-1) zoom 档位生效：实跑3条 zoom={sorted(set(zooms))} / var_01-03 zoom={vz}（variant_index 驱动）")

    # ---- (HOTFIX-3) quality_fail 诊断字段：实测值 + fail 字段 + 流信息 ----
    bs = b3data["batch_summary"]
    assert "quality_fail_fields_by_video" in bs, "batch_summary 应含 quality_fail_fields_by_video"
    for pv in b3data["per_variant"]:
        assert "quality_fail_fields" in pv and "quality_detail" in pv, pv
        qd = pv["quality_detail"]
        for kk in ("loudness_ok", "true_peak_ok", "clipping_ok", "playback_ok", "pts_ok", "duration_ok",
                   "measured_integrated_loudness_lufs", "measured_true_peak_dbtp",
                   "sample_rate", "channels", "codec"):
            assert kk in qd, f"quality_detail 缺 {kk}: {qd}"
        # 本批音频达标 → 有实测 LUFS/TP，且 codec/sr/channels 已回填（B2.7 重编码后音频未丢元信息）
        assert qd["measured_integrated_loudness_lufs"] is not None, qd
        assert qd["measured_true_peak_dbtp"] is not None, qd
        assert qd["codec"] == "aac" and qd["sample_rate"] == "44100" and qd["channels"] == 2, qd
    print("  ✔ (HOTFIX-3) quality 诊断字段：measured_loudness/TP + clipping/playback/pts/duration + codec/sr/channels 全回填")

    # ---- (HOTFIX-2) group_type 预检：3 条全同组 FAIL FAST；跨组 OK ----
    from services import p2b_b_service as bsvc
    same_group = [e["execution_plan_id"] for e in elig_on if e["group_type"] == "pain_first"][:3]
    se = _db.SessionLocal()
    pre_bad = bsvc.precheck_visual_diff_sample(se, "tenantA", same_group)
    pre_good = bsvc.precheck_visual_diff_sample(se, "tenantA", plan_ids_on)
    se.close()
    assert pre_bad["ok"] is False and pre_bad["distinct_groups"] == ["pain_first"], pre_bad
    assert "pain_first / selling_first / result_close" in pre_bad["reason"], pre_bad
    assert pre_good["ok"] is True and len(pre_good["distinct_groups"]) == 3, pre_good
    # preview API 也带预检 + recent_runs 防呆（用有效源，确保进到预检字段）
    src_pv = _make_mother("tenantA", 40)
    pv = c.post("/api/p2b-b/runs/preview", json={"production_order_id": po1,
                "execution_plan_ids": same_group, "source_video_id": src_pv, "max_items": 3},
                headers=A).json()
    assert pv["code"] == 0, pv
    assert pv["data"]["visual_diff_precheck"]["ok"] is False, pv["data"]["visual_diff_precheck"]
    assert "recent_runs" in pv["data"], "preview 应带 recent_runs 防呆"
    assert any(r["run_id"] == run_on for r in pv["data"]["recent_runs"]), "recent_runs 应含本次 run"
    print("  ✔ (HOTFIX-2) group_type 预检：3条全同组 FAIL FAST（提示跨组），跨组 OK；preview 附预检+recent_runs 防呆")

    # ---- (14) B3 可间接评估视觉差异：ON 的 visual_distance 均值 ≥ OFF ----
    assert vmean_on >= vmean_off, f"B2.7 应提升视觉差异 on={vmean_on:.4f} >= off={vmean_off:.4f}"
    print(f"  ✔ (14) B3 评估视觉差异：vmean_off={vmean_off:.4f} → vmean_on={vmean_on:.4f}（B2.7 拉开像素差异）")

    # ---- (9) 不新增表 / (10) 不改 schema ----
    assert _tables() == tables0, "B2.7 不得新增表 / 改 schema"
    print("  ✔ (9) 不新增表 / (10) 不改 DB schema")

    # ---- (11) 路由契约不变（B2.7 无新增 endpoint，B 台契约正常）----
    assert c.get(f"/api/p2b-b/runs/{run_on}", headers=A).json()["code"] == 0
    assert c.get(f"/api/p2b-b/runs/{run_on}/items", headers=A).json()["code"] == 0
    print("  ✔ (11) 路由契约不变（B2.7 无新增 endpoint，B 台 API 正常）")

    # ---- (16) production 403：B2.7 随 B 台 runs 一起被 production 拦截，永不触发 ----
    config.settings.app_env = "production"
    r = c.post("/api/p2b-b/runs", json={"production_order_id": po1,
               "execution_plan_ids": ["dummy"], "source_video_id": 1, "max_items": 3}, headers=A)
    assert r.status_code == 403, f"production 必须 403（B2.7 永不在 production 触发），got {r.status_code}"
    config.settings.app_env = "staging"
    print("  ✔ (16) production 403：B2.7 随 B 台 runs 被拦截，production 永不触发")

    # 落样例
    se = _db.SessionLocal()
    sample = {vid: json.loads(se.get(Video, vid).meta).get("visual_encoding") for vid in vids}
    se.close()
    with open(os.path.join(_SAMPLE_DIR, "visual_encoding_sample.json"), "w", encoding="utf-8") as f:
        json.dump({"visual_encoding_by_video": sample,
                   "b3_visual_distance_off": round(vmean_off, 4),
                   "b3_visual_distance_on": round(vmean_on, 4)}, f, ensure_ascii=False, indent=2)

    _db.engine.dispose()
    if os.path.exists("./_v4p2bb27_test.db"):
        os.remove("./_v4p2bb27_test.db")
    print("\n✅ V4 P2B-B2.7 ALL PASSED（17/17 + HOTFIX zoom/precheck/quality诊断）")


if __name__ == "__main__":
    main()
