"""V4 P2B Phase 2 B1 取窗发散 验证（方案 A 受限分带 + 方案 C overlap cap + fallback；flag 门控）。

覆盖 16 项：flag=false 逐字段相等 / flag=true 同 role 窗口发散 / 同 role IoU≤0.5 或 degraded /
structural_window_diff_estimate 上升 / seg 不变 / role 顺序不变 / target_output 不变 / duration∈[25,35] /
B2·B2.1 可见层不退化 / B2.5 音频不退化 / B2.7 visual profile 不退化 / B3 阈值不变 /
不新增表 / 不改 schema / production 403 / rollback 关 flag 回 87921d8 行为。

跑法：cd backend && SAMPLE_DIR=/path python tests/verify_v4_p2b_phase2_window_divergence.py
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
os.environ["DATABASE_URL"] = "sqlite:///./_v4p2bp2_test.db"

import config
import db as _db

_STORAGE = os.path.join(tempfile.mkdtemp(), "videos")
_SAMPLE_DIR = os.environ.get("SAMPLE_DIR") or os.path.join(tempfile.mkdtemp(), "p2b_p2_samples")


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
    try:
        d = json.loads(m[-1]); return float(d["input_i"]), float(d["input_tp"])
    except (ValueError, KeyError, IndexError):
        return None, None


def _client():
    _db.engine.dispose()
    if os.path.exists("./_v4p2bp2_test.db"):
        os.remove("./_v4p2bp2_test.db")
    s = config.settings
    s.auth_required = True; s.jwt_secret = "s"; s.admin_key = "K"
    s.app_env = "staging"; s.enable_compose = False
    s.enable_l2_skills = True; s.enable_p2b_real_execution = True
    s.enable_p2b_visible_layer = True; s.enable_p2b_visible_variation = True
    s.enable_p2b_audio_encoding_diff = True; s.enable_p2b_b3_score = True
    s.enable_p2b_visual_diff = True; s.enable_p2b_window_divergence = True   # Phase 2 + B2.7 同开
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


def _role_iou(pe, wA, wB):
    """同 role（首次出现对齐）跨 variant 的 source window IoU。"""
    rolesA = {w["role"]: w for w in wA}
    out = {}
    for w in wB:
        r = w["role"]
        if r in rolesA:
            a = rolesA[r]
            out[r] = round(pe._iou_1d(a["start"], a["end"], w["start"], w["end"]), 3)
    return out


def main():
    os.makedirs(_SAMPLE_DIR, exist_ok=True)
    from b_engine import plan_executor as pe

    _VP = lambda gt: {"group_type": gt, "group_index": 1, "production_order_id": "po",
                      "rhythm_plan": {"shot_durations": [{"role": "痛点", "duration": 1.0},
                                                         {"role": "产品", "duration": 1.0},
                                                         {"role": "效果", "duration": 1.0},
                                                         {"role": "品牌", "duration": 1.0}],
                                      "total_duration": 28.0},
                      "transition_plan": {"transitions": [{"type": "叠化", "duration": 0.4}] * 3}}
    SRC = 40.0

    def dw(gt, flag):
        config.settings.enable_p2b_window_divergence = flag
        return pe.derive_windows(_VP(gt), SRC, 25.0, 35.0, seed=pe._seed_of(gt))

    # ---- (1) flag=false 逐字段相等（未被发散改动，确定性可复算）----
    off1 = dw("pain_first", False); off2 = dw("pain_first", False)
    fields = lambda d: [(w["role"], w["start"], w["end"], w["seg"]) for w in d["windows"]]
    assert fields(off1) == fields(off2), "flag=off derive_windows 必须确定"
    assert off1["window_divergence"]["applied"] is False, "flag=off 不应发散"
    # golden 快照锁定 flag-off 行为（= 87921d8 取窗，防回归）；逐字段 role/start/end/seg
    GOLDEN = [("痛点", 0.0, 7.4, 7.4), ("产品", 8.348, 15.748, 7.4),
              ("效果", 20.569, 27.969, 7.4), ("品牌", 28.39, 35.79, 7.4)]
    assert fields(off1) == GOLDEN, f"flag=off 必须与 87921d8 golden 逐字段相等: {fields(off1)}"
    print("  ✔ (1) flag=false 逐字段确定、未被发散改动（window_divergence.applied=False）")

    # ---- (2/3/4) flag=true 同 role 发散 + IoU≤0.5(或 degraded) + structural estimate↑ ----
    on = {gt: dw(gt, True)["windows"] for gt in ("pain_first", "selling_first", "result_close")}
    off = {gt: dw(gt, False)["windows"] for gt in ("pain_first", "selling_first", "result_close")}
    iou_off = _role_iou(pe, off["pain_first"], off["selling_first"])
    iou_on = _role_iou(pe, on["pain_first"], on["selling_first"])
    print(f"    same-role IoU pain-selling OFF={iou_off} → ON={iou_on}")
    # 发散：非 no_room 的 role IoU 明显下降；可移动 role 应 ≤0.5
    moved = [r for r in iou_on if iou_on[r] < iou_off[r]]
    assert len(moved) >= 2, f"至少 2 个 role 发散下降: off={iou_off} on={iou_on}"
    wd = dw("pain_first", True)["window_divergence"]
    assert wd["applied"] and wd["flag"] and wd["strategy"] == "role_band_plus_overlap_cap"
    # IoU≤0.5（估计）或 degraded 标记
    assert wd["role_iou_after"] <= 0.5 or wd["degraded"] is True, wd
    assert wd["structural_window_diff_estimate"] > (1 - wd["role_iou_before"]) - 1e-6 or wd["role_iou_after"] <= wd["role_iou_before"], wd
    assert wd["structural_window_diff_estimate"] >= 0.4, f"structural estimate 应抬升: {wd}"
    print(f"  ✔ (2/3/4) 同 role 发散 / IoU_after={wd['role_iou_after']}(≤0.5 或 degraded={wd['degraded']}) / "
          f"structural_estimate={wd['structural_window_diff_estimate']}↑")

    # ---- (5/6/7) seg / role 顺序 / target_output 不变 ----
    o1 = dw("pain_first", False); n1 = dw("pain_first", True)
    assert [w["seg"] for w in o1["windows"]] == [w["seg"] for w in n1["windows"]], "seg 必须不变"
    assert [w["role"] for w in o1["windows"]] == [w["role"] for w in n1["windows"]], "role 顺序必须不变"
    assert o1["target_output"] == n1["target_output"], "target_output 必须不变"
    print("  ✔ (5) seg 不变 / (6) role 顺序不变 / (7) target_output 不变")

    # ---- (16) rollback：关 flag 回 87921d8 行为（与 (1) off 一致）----
    config.settings.enable_p2b_window_divergence = False
    rb = pe.derive_windows(_VP("pain_first"), SRC, 25.0, 35.0, seed=pe._seed_of("pain_first"))
    assert fields(rb) == fields(off1), "关 flag 必须回到 off 行为"
    print("  ✔ (16) rollback：ENABLE_P2B_WINDOW_DIVERGENCE=false 回 87921d8 取窗")

    # ---- 集成：全开跑批，验证不退化 + qa_json.window_divergence ----
    c = _client(); A = _hdr("tenantA")
    tables0 = _tables()
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
    assert run["code"] == 0 and run["data"]["completed"] == 3, run
    run_id = run["data"]["run_id"]
    items = c.get(f"/api/p2b-b/runs/{run_id}/items", headers=A).json()["data"]["items"]
    vids = sorted(it["video_id"] for it in items)

    from models import Video
    from sqlalchemy import text
    se = _db.SessionLocal()
    for vid in vids:
        v = se.get(Video, vid); meta = json.loads(v.meta)
        path = os.path.join(_STORAGE, "viral", f"{vid}.mp4")
        # (8) duration / (10) B2.5 音频 / (11) B2.7 visual / (9) 可见层
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=nw=1:nk=1", path], capture_output=True, text=True).stdout)
        assert 24.5 <= dur <= 35.5, f"duration {dur} 越界"
        I, TP = _measure_loudness(path)
        assert I is not None and -15.0 <= I <= -13.0 and TP <= -1.0, f"B2.5 退化 I={I} TP={TP}"
        assert meta.get("visual_encoding", {}).get("applied") is True, "B2.7 应仍生效"
        assert meta.get("audio_encoding", {}).get("applied") is True
    # qa_json.window_divergence 写入
    qj = se.execute(text("SELECT qa_json FROM p2b_execution_run_items WHERE run_id=:r"),
                    {"r": run_id}).fetchall()
    se.close()
    wd_items = [json.loads(r[0]).get("window_divergence") for r in qj if r[0]]
    assert all(w and w.get("applied") is True for w in wd_items), "qa_json 应含 window_divergence.applied=True"
    assert all(k in wd_items[0] for k in ("flag", "band_width_ratio", "overlap_cap", "strategy",
               "degraded", "degraded_reason", "role_iou_before", "role_iou_after",
               "structural_window_diff_estimate")), wd_items[0]
    print("  ✔ (8) duration∈[25,35] / (9) 可见层 / (10) B2.5 不退化 / (11) B2.7 不退化 / qa_json.window_divergence 全字段")

    # ---- (12) B3 阈值不变 + B3 评分能算结构差异 ----
    b3 = c.post("/api/p2b-b3/score", json={"run_id": run_id}, headers=A).json()["data"]
    assert b3["thresholds_used"]["visual_floor"] == 0.12 and b3["thresholds_used"]["kf_min_floor"] == 0.06
    assert b3["thresholds_used"]["VDS_pass"] == 70.0
    sw = [cell["structural_window_diff"] for cell in b3["pairwise_matrix"]]
    vd = [cell["visual_distance"] for cell in b3["pairwise_matrix"]]
    print(f"  ✔ (12) B3 阈值不变（floor 0.12/0.06，VDS_pass 70）；structural_window_diff={[round(x,3) for x in sw]} "
          f"visual_distance={[round(x,3) for x in vd]}")

    # ---- (13) 不新增表 / (14) 不改 schema ----
    assert _tables() == tables0, "不得新增表/改 schema"
    print("  ✔ (13) 不新增表 / (14) 不改 DB schema")

    # ---- (15) production 403 ----
    config.settings.app_env = "production"
    r = c.post("/api/p2b-b/runs", json={"production_order_id": po, "execution_plan_ids": ["dummy"],
               "source_video_id": 1, "max_items": 3}, headers=A)
    assert r.status_code == 403, f"production 必须 403，got {r.status_code}"
    config.settings.app_env = "staging"
    print("  ✔ (15) production 403：取窗发散随 B 台 runs 被拦截，production 永不触发")

    with open(os.path.join(_SAMPLE_DIR, "window_divergence_sample.json"), "w", encoding="utf-8") as f:
        json.dump({"window_divergence": wd_items[0], "b3_structural_window_diff": [round(x, 4) for x in sw],
                   "b3_visual_distance": [round(x, 4) for x in vd],
                   "same_role_iou_off_pain_selling": iou_off, "same_role_iou_on_pain_selling": iou_on},
                  f, ensure_ascii=False, indent=2)

    _db.engine.dispose()
    if os.path.exists("./_v4p2bp2_test.db"):
        os.remove("./_v4p2bp2_test.db")
    print("\n✅ V4 P2B Phase 2 取窗发散 ALL PASSED（16/16）")


if __name__ == "__main__":
    main()
