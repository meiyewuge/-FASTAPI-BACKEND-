"""V4 P2B-B3 三维差异评分闸门 验证（只评分，不自动重剪/不生成/不扩批）。

覆盖 20 项：只评分本 batch 3 条 / 不生成新 mp4 / 不改 videos.status / pairwise 3 对完整 /
visual·text·audio·quality·VDS 全输出 / recommended_action 仅三值 / 商业指标存在 /
b3_score 写 meta / b3_batch 写 qa_json / 幂等覆盖不追加 / calibration=provisional /
quality 复用 B2.5 标准(-14±1, TP≤-1) / production 403 / B1-B2.5 不退化 /
大 N 模拟 N=50/100 / O(N²) 降级 N>30 生效 / visual_proxy_only·pixel_verified 记录 /
不调火山 / 不新增表 / cost=0。

跑法：cd backend && SAMPLE_DIR=/path python tests/verify_v4_p2b_b3.py
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
os.environ["DATABASE_URL"] = "sqlite:///./_v4p2bb3_test.db"

import config
import db as _db

_STORAGE = os.path.join(tempfile.mkdtemp(), "videos")
_SAMPLE_DIR = os.environ.get("SAMPLE_DIR") or os.path.join(tempfile.mkdtemp(), "p2b_b3_samples")
_VALID_ACTIONS = {"pass_to_publish_pool", "manual_review", "needs_regeneration_later"}


def _make_source(path, seconds, w=320, h=240, audio=True):
    # 宽带高 crest 源（与 B2.5 一致），保证 B2.5 音频链路达标、B3 quality 可复用 B2.5 标准
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


def _client():
    _db.engine.dispose()
    if os.path.exists("./_v4p2bb3_test.db"):
        os.remove("./_v4p2bb3_test.db")
    s = config.settings
    s.auth_required = True; s.jwt_secret = "s"; s.admin_key = "K"
    s.app_env = "staging"; s.enable_compose = False
    s.enable_l2_skills = True; s.enable_p2b_real_execution = True
    s.enable_p2b_visible_layer = True; s.enable_p2b_visible_variation = True
    s.enable_p2b_audio_encoding_diff = True; s.enable_p2b_b3_score = True
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
    c = _client()
    A = _hdr("tenantA")

    import httpx
    trig = {"n": 0}
    def _boom(*a, **k):
        trig["n"] += 1
        raise AssertionError("不应触发火山/HTTP")
    httpx.post = httpx.get = _boom

    from models import Video
    from b_engine import b3_score

    # ---- 前置：P2A + P2B-A confirm + 选 3 + 真实执行 3 条（B1/B2/B2.1/B2.5 底座）----
    dp = c.post("/api/compose/preview",
                json={"prompt": "达芙荻丽修复精华，痛点皱纹暗沉，产品展示质地，效果对比7天，品牌定格，关注领取试用装",
                      "style": "premium", "ratio": "9:16", "duration": 30, "resolution": "1080p"},
                headers=A).json()["data"]["director_plan_id"]
    po = c.post("/api/production-orders",
                json={"director_plan_id": dp, "scenario": "product_seeding", "platform": "douyin"},
                headers=A).json()["data"]["production_order_id"]
    assert c.post("/api/p2b/execution-plans", json={"production_order_id": po}, headers=A).json()["data"]["total"] == 30
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
    run_id = run["data"]["run_id"]
    items = c.get(f"/api/p2b-b/runs/{run_id}/items", headers=A).json()["data"]["items"]
    scored_ids = sorted(it["video_id"] for it in items)
    print(f"  ✔ 前置：B1/B2/B2.1/B2.5 真实执行 3 条成功（video_ids={scored_ids}）")

    # 基线快照（用于"不退化/不生成/不改 status/不新增表"对比）
    tables_before = _tables()
    se = _db.SessionLocal()
    status_before = {v.id: (v.storage_status, v.type) for v in se.query(Video).all()}
    se.close()
    viral_dir = os.path.join(_STORAGE, "viral")
    mp4_before = sorted(f for f in os.listdir(viral_dir) if f.endswith(".mp4"))

    # (14) B2.5 不退化 + (12 准备) 三条音频达标（-14±1 / TP≤-1）
    lufs_list = []
    for it in items:
        path = os.path.join(viral_dir, f"{it['video_id']}.mp4")
        I, TP = _measure_loudness(path)
        lufs_list.append((it["video_id"], I, TP))
        assert I is not None and -15.0 <= I <= -13.0, f"B2.5 退化 I={I}"
        assert TP is not None and TP <= -1.0, f"B2.5 退化 TP={TP}"
    print(f"  ✔ (14) B1-B2.5 不退化：3 条 I=-14±1 / TP≤-1  {['%.2f/%.2f'%(I,TP) for _,I,TP in lufs_list]}")

    # ---- B3 评分 ----
    r = c.post("/api/p2b-b3/score", json={"run_id": run_id}, headers=A).json()
    assert r["code"] == 0, r
    data = r["data"]

    # (1) 只评分本 batch 3 条
    assert data["batch_id"] == run_id
    assert sorted(data["video_ids"]) == scored_ids, "应只评分本 batch 三条"
    print("  ✔ (1) 只评分本 batch 3 条（不触历史样片）")

    # (2) 不生成新 mp4 + (3) 不改 videos.status
    mp4_after = sorted(f for f in os.listdir(viral_dir) if f.endswith(".mp4"))
    assert mp4_after == mp4_before, "B3 不得生成/删除 mp4"
    se = _db.SessionLocal()
    status_after = {v.id: (v.storage_status, v.type) for v in se.query(Video).all()}
    se.close()
    assert status_after == status_before, "B3 不得修改 videos.status/type"
    print("  ✔ (2) 不生成新 mp4 / (3) 不改 videos.status")

    # (4) pairwise 3 对完整 + (5) 五类分全输出
    matrix = data["pairwise_matrix"]
    assert len(matrix) == 3, f"pairwise 应 3 对，实际 {len(matrix)}"
    need = ["visual_distance", "text_distance", "audio_distance", "visual_score", "ocr_score",
            "audio_score", "quality_score", "VDS_total", "pair_pass", "pair_status", "pair_flags"]
    for cell in matrix:
        for kk in need:
            assert kk in cell, f"matrix cell 缺 {kk}"
        assert 0 <= cell["VDS_total"] <= 100
    print("  ✔ (4) pairwise 3 对完整 / (5) visual·text·audio·quality·VDS 全输出")

    # (6) recommended_action 仅三值 + (7) 商业指标
    for p in data["per_variant"]:
        assert p["recommended_action"] in _VALID_ACTIONS, p
        for kk in ("visual_score", "ocr_score", "audio_score", "quality_score", "VDS_total", "fail_reason"):
            assert kk in p
    bs = data["batch_summary"]
    assert bs["recommended_action"] in _VALID_ACTIONS
    assert "effective_variant_count" in bs and "batch_pass_rate" in bs
    assert bs["total_variant_count"] == 3
    assert 0.0 <= bs["batch_pass_rate"] <= 1.0
    assert bs["effective_variant_count"] == sum(1 for p in data["per_variant"]
                                                if p["recommended_action"] == "pass_to_publish_pool")
    print(f"  ✔ (6) recommended_action 仅三值 / (7) effective={bs['effective_variant_count']} "
          f"pass_rate={bs['batch_pass_rate']}")

    # (11) calibration=provisional
    assert data["thresholds_used"]["calibration"] == "provisional", data["thresholds_used"]
    assert data["b3_version"] == "b3_v1"
    print("  ✔ (11) thresholds_used.calibration=provisional（负样本未到位不锁定）")

    # (8) b3_score 写入 videos.meta + (9) b3_batch 写入 run_items.qa_json
    se = _db.SessionLocal()
    for vid in scored_ids:
        v = se.get(Video, vid)
        meta = json.loads(v.meta)
        assert "b3_score" in meta, "videos.meta 应含 b3_score"
        assert meta["b3_score"]["recommended_action"] in _VALID_ACTIONS
        assert meta["b3_score"]["batch_id"] == run_id
    from sqlalchemy import text
    qj_rows = se.execute(text("SELECT qa_json FROM p2b_execution_run_items WHERE run_id=:r"),
                         {"r": run_id}).fetchall()
    b3_batch_count = sum(1 for row in qj_rows if row[0] and "b3_batch" in json.loads(row[0]))
    se.close()
    assert b3_batch_count >= 1, "run_items.qa_json 应含 b3_batch"
    print("  ✔ (8) b3_score 写入 videos.meta / (9) b3_batch 写入 run_items.qa_json")

    # (12) quality 复用 B2.5 标准（-14±1, TP≤-1）：质量项判定线对齐，三条质量全过
    assert b3_score.LUFS_LO == -15.0 and b3_score.LUFS_HI == -13.0 and b3_score.TP_ACCEPT_DBTP == -1.0
    for p in data["per_variant"]:
        assert p["quality_score"] > 0, p
    for cell in matrix:
        assert "quality_fail" not in cell["pair_flags"], f"三条达标不应 quality_fail: {cell}"
    print("  ✔ (12) quality 复用 B2.5 标准 -14±1/TP≤-1（内部 -2 仅处理目标，非判定线），三条质量全过")

    # (10) 幂等覆盖不追加：重跑，b3_batch 数量与字段不重复累积
    se = _db.SessionLocal()
    meta_keys_before = len(json.loads(se.get(Video, scored_ids[0]).meta).keys())
    se.close()
    r2 = c.post("/api/p2b-b3/score", json={"run_id": run_id}, headers=A).json()
    assert r2["code"] == 0
    se = _db.SessionLocal()
    meta2 = json.loads(se.get(Video, scored_ids[0]).meta)
    qj2 = se.execute(text("SELECT qa_json FROM p2b_execution_run_items WHERE run_id=:r LIMIT 1"),
                     {"r": run_id}).fetchone()
    se.close()
    assert len(meta2.keys()) == meta_keys_before, "重跑不应新增 meta key（幂等覆盖）"
    qa2 = json.loads(qj2[0])
    assert list(qa2.keys()).count("b3_batch") <= 1
    assert qa2["b3_batch"]["batch_id"] == run_id
    print("  ✔ (10) 重跑幂等覆盖，不追加")

    # 发布池契约
    pp = c.get(f"/api/p2b-b3/publish-pool/{run_id}", headers=A).json()["data"]
    assert pp["contract"] == "batch_summary.pass=true AND recommended_action=pass_to_publish_pool"
    if pp["batch_pass"]:
        assert all(vid in scored_ids for vid in pp["videos"])
    print(f"  ✔ 发布池契约：eligible={pp['eligible']} videos={pp['videos']}")

    # (15) 大 N 模拟 N=50/100 + (16) O(N²) 降级 + (17) proxy/pixel 记录
    for N in (50, 100):
        sim = c.post("/api/p2b-b3/simulate", json={"production_order_id": po, "n": N}, headers=A).json()["data"]
        assert sim["N"] == N
        for kk in ("signature_duplicate_count", "visible_signature_duplicate_count",
                   "audio_signature_duplicate_count", "too_similar_candidate_count",
                   "candidate_pair_count", "bucket_density", "collision_hotspots",
                   "visual_proxy_only_count", "pixel_verified_candidate_count",
                   "structure_only_risk", "pixel_verified_risk"):
            assert kk in sim, f"大 N 模拟缺 {kk}"
        # (16) N>30 → 降级生效，候选对 < 全量
        assert sim["downgrade_applied"] is True, f"N={N} 应触发 O(N²) 降级"
        assert sim["candidate_pair_count"] < sim["full_pairs_if_naive"], "降级后候选对应少于全量"
        # (17) 无真实帧 → 全 proxy，pixel_verified=0，结构风险与像素风险分开记
        assert sim["pixel_verified_candidate_count"] == 0 and sim["visual_proxy_only_count"] > 0
        assert sim["pixel_verified_risk"] == 0
        print(f"  ✔ (15/16/17) N={N}: 候选对 {sim['candidate_pair_count']}/{sim['full_pairs_if_naive']}（降级）"
              f" 重复sig={sim['visible_signature_duplicate_count']} "
              f"structure_only_risk={sim['structure_only_risk']} pixel_verified={sim['pixel_verified_candidate_count']}")

    # (13) production 403 不退化
    config.settings.app_env = "production"
    assert c.post("/api/p2b-b3/score", json={"run_id": run_id}, headers=A).status_code == 403
    assert c.post("/api/p2b-b3/simulate", json={"production_order_id": po, "n": 50}, headers=A).status_code == 403
    config.settings.app_env = "staging"
    print("  ✔ (13) production 403 不退化（score + simulate 均拦截）")

    # (18) 不调火山 + (19) 不新增表 + (20) cost=0
    assert trig["n"] == 0, "B3 不应触发任何 HTTP/火山/LLM"
    assert _tables() == tables_before, "B3 不得新增表"
    se = _db.SessionLocal()
    amt = se.execute(text("SELECT COALESCE(SUM(amount),0) FROM cost_records WHERE api_name LIKE 'video.p2b%'")).scalar()
    se.close()
    assert (amt or 0) == 0, f"B3 cost 应为 0，实际 {amt}"
    print("  ✔ (18) 不调火山/LLM / (19) 不新增表 / (20) cost=0")

    # 落样例报告
    with open(os.path.join(_SAMPLE_DIR, "b3_batch_result.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    _db.engine.dispose()
    if os.path.exists("./_v4p2bb3_test.db"):
        os.remove("./_v4p2bb3_test.db")
    print("\n✅ V4 P2B-B3 ALL PASSED（20/20）")


if __name__ == "__main__":
    main()
