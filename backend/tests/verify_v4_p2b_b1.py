"""V4 P2B-B1 Small Batch Real Execution 验证。

验证「后期制作脑子 → 执行器 → 成片」闭环：从 P2B-A confirmed execution_plans 选 3 条
（pain_first/selling_first/result_close），绑定真实 source_video_id，真实生成 3 条视频。

覆盖：source 硬校验 / 双闸门(staging+flag, production 403) / 3 条成片 / duration∈[25,35] /
AAC / playback / PTS / MD5 3-3 唯一 / cost=0 / videos(type=viral,batch_id=run_id) /
run_items 状态 / 不写 P2A·P2B-A 表 / transition 执行证据 / fallback 字段 / tenant 隔离 / 不调火山。

跑法：cd backend && SAMPLE_DIR=/path python tests/verify_v4_p2b_b1.py
"""
import json
import os
import subprocess
import sys
import tempfile

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
os.environ["DATABASE_URL"] = "sqlite:///./_v4p2bb1_test.db"

import config
import db as _db

_STORAGE = os.path.join(tempfile.mkdtemp(), "videos")
_SAMPLE_DIR = os.environ.get("SAMPLE_DIR") or os.path.join(tempfile.mkdtemp(), "p2b_b1_samples")


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
    if os.path.exists("./_v4p2bb1_test.db"):
        os.remove("./_v4p2bb1_test.db")
    s = config.settings
    s.auth_required = True; s.jwt_secret = "s"; s.admin_key = "K"
    s.app_env = "staging"; s.enable_compose = False
    s.enable_l2_skills = True               # 需开 P2B-A 才能 confirm plans
    s.enable_p2b_real_execution = False     # 默认关闭，先测闸门
    s.storage_dir = _STORAGE
    s.storage_base_url = "https://test.local/static/videos"
    s.b_remix_target_lo = 25.0; s.b_remix_target_hi = 35.0
    s.b_remix_width = 320; s.b_remix_height = 240; s.b_remix_fps = 30
    from fastapi.testclient import TestClient
    from main import app
    _db.init_db()
    from migrations import p2a_init, p2b_a_init, p2b_b1_init
    p2a_init.run(); p2b_a_init.run()
    mig = p2b_b1_init.run()
    return TestClient(app), mig


def _hdr(tenant, phone=None):
    from utils import jwt_util
    return {"Authorization": f"Bearer {jwt_util.encode({'tenant_id': tenant, 'phone': phone or tenant}, 's')}"}


def _count(table):
    from sqlalchemy import text
    se = _db.SessionLocal()
    try:
        return se.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
    finally:
        se.close()


def _make_mother(tenant, seconds=40, audio=True):
    from models import Video
    se = _db.SessionLocal()
    v = Video(tenant_id=tenant, type="mother", source_type="uploaded", title="母", duration_seconds=seconds)
    se.add(v); se.commit(); vid = v.id; se.close()
    os.makedirs(os.path.join(_STORAGE, "mother"), exist_ok=True)
    _make_source(os.path.join(_STORAGE, "mother", f"{vid}.mp4"), seconds, audio=audio)
    return vid


def main():
    os.makedirs(_SAMPLE_DIR, exist_ok=True)
    c, mig = _client()
    A = _hdr("tenantA"); B = _hdr("tenantB")

    import httpx
    trig = {"n": 0}
    def _boom(*a, **k):
        trig["n"] += 1
        raise AssertionError("P2B-B1 不应触发火山/HTTP")
    httpx.post = httpx.get = _boom

    from sqlalchemy import inspect
    tables = set(inspect(_db.engine).get_table_names())

    # ---- migration：只新增 2 表 ----
    assert "p2b_execution_runs" in tables and "p2b_execution_run_items" in tables
    assert "idx_pbr_tenant" in mig["runs_indexes"] and "idx_pri_tenant" in mig["items_indexes"]
    print("  ✔ migration 新增 2 表（runs/run_items）+ tenant 索引")

    # ---- P2A 生产单 + P2B-A confirm 30 条 ----
    dp = c.post("/api/compose/preview",
                json={"prompt": "达芙荻丽修复精华，痛点皱纹暗沉，产品展示质地，效果对比7天，品牌定格，关注领取",
                      "style": "premium", "ratio": "9:16", "duration": 30, "resolution": "1080p"},
                headers=A).json()["data"]["director_plan_id"]
    po = c.post("/api/production-orders",
                json={"director_plan_id": dp, "scenario": "product_seeding", "platform": "douyin"},
                headers=A).json()["data"]["production_order_id"]
    cf = c.post("/api/p2b/execution-plans", json={"production_order_id": po}, headers=A).json()
    assert cf["code"] == 0 and cf["data"]["total"] == 30, cf
    ep_before = _count("execution_plans")
    print(f"  ✔ 前置：P2A 生产单 + P2B-A confirm 30 条（execution_plans={ep_before}）")

    # ---- eligible-plans：选 3 条（pain_first/selling_first/result_close）----
    elig = c.get(f"/api/p2b-b/eligible-plans/{po}", headers=A).json()["data"]["items"]
    assert len(elig) == 30 and all(e["execute_ready"] for e in elig), "应 30 条且 execute_ready"
    pick = {}
    for e in elig:
        if e["group_type"] in ("pain_first", "selling_first", "result_close") and e["group_type"] not in pick:
            pick[e["group_type"]] = e["execution_plan_id"]
    plan_ids = [pick["pain_first"], pick["selling_first"], pick["result_close"]]
    assert len(plan_ids) == 3, pick
    print("  ✔ eligible-plans 30 条；选定 pain_first/selling_first/result_close 各 1")

    # ---- 真实源视频 + 源硬校验 ----
    src_id = _make_mother("tenantA", 40, audio=True)
    short_id = _make_mother("tenantA", 5, audio=True)     # 时长不足
    # 不存在
    assert c.post("/api/p2b-b/runs/preview",
                  json={"production_order_id": po, "execution_plan_ids": plan_ids,
                        "source_video_id": 999999, "max_items": 3}, headers=A).json()["code"] == 2002
    # 时长不足
    assert c.post("/api/p2b-b/runs/preview",
                  json={"production_order_id": po, "execution_plan_ids": plan_ids,
                        "source_video_id": short_id, "max_items": 3}, headers=A).json()["code"] == 2002
    # 缺陷源（临时把 src_id 标为缺陷）
    _orig_defect = list(config.settings.p2b_b1_defect_source_ids)
    config.settings.p2b_b1_defect_source_ids = [src_id]
    assert c.post("/api/p2b-b/runs/preview",
                  json={"production_order_id": po, "execution_plan_ids": plan_ids,
                        "source_video_id": src_id, "max_items": 3}, headers=A).json()["code"] == 2002
    config.settings.p2b_b1_defect_source_ids = _orig_defect
    print("  ✔ source 硬校验：不存在/时长不足/缺陷源 → preview 即 2002")

    # ---- runs/preview 合法 ----
    pv = c.post("/api/p2b-b/runs/preview",
                json={"production_order_id": po, "execution_plan_ids": plan_ids,
                      "source_video_id": src_id, "max_items": 3}, headers=A).json()
    assert pv["code"] == 0 and pv["data"]["expected_outputs"] == 3 and pv["data"]["expected_cost"] == 0, pv
    assert all(25.0 <= it["target_output"] <= 35.0 for it in pv["data"]["selected"]), pv
    print("  ✔ runs/preview：3 条、target∈[25,35]、cost=0、不入库")

    # ---- 闸门：flag=false → 4031 ----
    assert c.post("/api/p2b-b/runs",
                  json={"production_order_id": po, "execution_plan_ids": plan_ids,
                        "source_video_id": src_id, "max_items": 3}, headers=A).json()["code"] == 4031
    # 闸门：production 强制 403（即使 flag=true）
    config.settings.enable_p2b_real_execution = True
    config.settings.app_env = "production"
    r403 = c.post("/api/p2b-b/runs",
                  json={"production_order_id": po, "execution_plan_ids": plan_ids,
                        "source_video_id": src_id, "max_items": 3}, headers=A)
    assert r403.status_code == 403, r403.status_code
    config.settings.app_env = "staging"
    # DTO 上限：max_items>6 → 422(2001)
    assert c.post("/api/p2b-b/runs",
                  json={"production_order_id": po, "execution_plan_ids": plan_ids,
                        "source_video_id": src_id, "max_items": 7}, headers=A).json()["code"] == 2001
    print("  ✔ 双闸门：flag=false→4031；production→403；max_items>6→2001")

    # ---- 真实执行 3 条（staging + flag=true）----
    po_before = _count("production_orders")
    run = c.post("/api/p2b-b/runs",
                 json={"production_order_id": po, "execution_plan_ids": plan_ids,
                       "source_video_id": src_id, "max_items": 3}, headers=A).json()
    assert run["code"] == 0, run
    rd = run["data"]
    assert rd["status"] == "done" and rd["completed"] == 3 and rd["failed"] == 0 and rd["cost"] == 0, rd
    run_id = rd["run_id"]
    print(f"  ✔ 真实执行 3 条成功（run={run_id}, completed=3, cost=0）")

    # ---- 不写 P2A/P2B-A 表 ----
    assert _count("execution_plans") == ep_before, "B1 不应改 execution_plans"
    assert _count("production_orders") == po_before, "B1 不应改 production_orders"
    print("  ✔ 不写 P2A/P2B-A 表（execution_plans/production_orders 数量不变）")

    # ---- run_items + videos 校验 ----
    items = c.get(f"/api/p2b-b/runs/{run_id}/items", headers=A).json()["data"]["items"]
    assert len(items) == 3 and all(it["status"] == "done" and it["video_id"] for it in items), items
    from b_engine import qa_checks
    from models import Video
    se = _db.SessionLocal()
    md5s, durs = set(), []
    transition_seen = False
    for it in items:
        v = se.get(Video, it["video_id"])
        assert v.type == "viral" and v.source_type == "remixed" and v.batch_id == run_id, (v.type, v.batch_id)
        assert v.parent_video_id == src_id, v.parent_video_id
        path = os.path.join(_STORAGE, "viral", f"{v.id}.mp4")
        assert os.path.exists(path), path
        ok, _ = qa_checks.playback_validate(path); assert ok, f"playback {it['video_id']}"
        pok, _ = qa_checks.pts_check(path); assert pok, f"pts {it['video_id']}"
        dur = qa_checks.probe_duration(path); assert 24.5 <= dur <= 35.5, f"dur={dur}"
        assert qa_checks.has_audio(path), "缺音轨"
        md5s.add(it["md5"]); durs.append(dur)
        # 转场执行证据：至少有一条 item 用到非 hard_cut（applied_duration>0）
        for t in (it.get("transition_applied") or []):
            if t.get("applied_duration", 0) and t["applied_duration"] > 0:
                transition_seen = True
        # 落盘样片
        import shutil
        shutil.copy(path, os.path.join(_SAMPLE_DIR, f"{it['group_type']}_{v.id}.mp4"))
    se.close()
    assert len(md5s) == 3, f"MD5 去重退化 {len(md5s)}/3"
    assert transition_seen, "应至少有一条执行了真实视觉转场（xfade）"
    print(f"  ✔ 3 视频：viral+batch_id=run_id / duration∈[25,35] / AAC / playback / PTS / MD5 3-3 唯一")
    print("  ✔ 转场执行证据：存在真实 xfade（applied_duration>0）")

    # ---- cost=0 ----
    from sqlalchemy import text
    se = _db.SessionLocal()
    amt = se.execute(text("SELECT COALESCE(SUM(amount),0) FROM cost_records WHERE api_name='video.p2b_b1'")).scalar()
    se.close()
    assert (amt or 0) == 0, f"cost={amt}"
    print("  ✔ cost=0（video.p2b_b1 成本合计 0）")

    # ---- get_run + tenant 隔离 ----
    assert c.get(f"/api/p2b-b/runs/{run_id}", headers=A).json()["data"]["status"] == "done"
    assert c.get(f"/api/p2b-b/runs/{run_id}", headers=B).json()["code"] == 3001
    assert c.get(f"/api/p2b-b/runs/{run_id}/items", headers=B).json()["data"]["total"] == 0
    print("  ✔ get_run/items 正常；tenant 隔离（B 看不到 A 的 run）")

    # ---- 不调火山 ----
    assert trig["n"] == 0, f"火山触发 {trig['n']}"
    print("  ✔ 不调火山（httpx 陷阱 0 次）")

    print(f"\n  样片目录（供人眼/人耳验收）：{_SAMPLE_DIR}")
    for f in sorted(os.listdir(_SAMPLE_DIR)):
        print(f"    {f}")

    _db.engine.dispose()
    if os.path.exists("./_v4p2bb1_test.db"):
        os.remove("./_v4p2bb1_test.db")
    print("\n✅ V4 P2B-B1 ALL PASSED")


if __name__ == "__main__":
    main()
