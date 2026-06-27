"""V4 P2A 验证：生产单 + 裂变计划 preview（6 表 / 12 技能 / 5 API / 安全锁）。

覆盖施工包 §7 验证清单 17 项：
1) 6 张新表存在
2) skill_registry 12 条种子
3) skill_id 精确集合校验
4) adapter 全部 snake_case（与 §2.7 完全一致）
5) production-orders/preview 返回 preview JSON，不入库
6) production-orders POST 创建 confirmed 生产单
7) production-orders/{id} 返回 order + shot_maps（含 tenant_id）
8) fission-plans/preview 返回 30 条 variant
9) 每条 variant 有 tenant_id
10) 每条 variant 的 skill_sequence 只用 12 条 canonical skill_id
11) GET /api/skills 返回 12 条
12) skill_executor mode=execute 抛异常
13) preview API cost=0（cost_ledger / cost_records 无新增）
14) 不触发火山（httpx 陷阱未触发）
15) 不调用 remixer（preview 路径未 import/调用）
16) 不写 videos 表（preview/create 不新增 videos）
17) P1.1 /b/batch-generate 回归正常

跑法：cd backend && python tests/verify_v4_p2a.py
"""
import os
import subprocess
import sys
import tempfile

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
os.environ["DATABASE_URL"] = "sqlite:///./_v4p2a_test.db"

import config
import db as _db

_STORAGE = os.path.join(tempfile.mkdtemp(), "videos")

# canonical 真值源（与施工包 §2.7 一致），独立硬编码用于交叉校验
CANONICAL = {
    "safe_trim_setpts_v1", "normalize_video_v1", "safe_concat_v1", "playback_validate_v1",
    "probe_video_v1", "shot_role_labeler_v1", "mother_segment_mapper_v1",
    "fission_strategy_planner_v1", "text_card_insert_v1", "product_image_insert_v1",
    "subtitle_brand_style_v1", "md5_duplicate_check_v1",
}
EXPECTED_ADAPTERS = {
    "safe_trim_setpts_v1": "safe_trim_setpts_adapter",
    "normalize_video_v1": "normalize_video_adapter",
    "safe_concat_v1": "safe_concat_adapter",
    "playback_validate_v1": "playback_validate_adapter",
    "probe_video_v1": "probe_video_adapter",
    "shot_role_labeler_v1": "shot_role_labeler_adapter",
    "mother_segment_mapper_v1": "mother_segment_mapper_adapter",
    "fission_strategy_planner_v1": "fission_strategy_planner_adapter",
    "text_card_insert_v1": "text_card_insert_adapter",
    "product_image_insert_v1": "product_image_insert_adapter",
    "subtitle_brand_style_v1": "subtitle_brand_style_adapter",
    "md5_duplicate_check_v1": "md5_duplicate_check_adapter",
}


def _mp4(path):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=1",
         "-pix_fmt", "yuv420p", path],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _client():
    _db.engine.dispose()
    if os.path.exists("./_v4p2a_test.db"):
        os.remove("./_v4p2a_test.db")
    config.settings.auth_required = True
    config.settings.jwt_secret = "s"
    config.settings.admin_key = "K"
    config.settings.enable_compose = False
    config.settings.storage_dir = _STORAGE
    config.settings.storage_base_url = "https://test.local/static/videos"
    # P1.1 提速：缩小裂变目标时长/分辨率（仅测试，不改生产口径）
    config.settings.b_remix_target_lo = 2.0
    config.settings.b_remix_target_hi = 4.0
    config.settings.b_remix_width = 320
    config.settings.b_remix_height = 240
    from fastapi.testclient import TestClient
    from main import app
    _db.init_db()
    # 触发 P2A 表创建 + 种子
    from migrations import p2a_init
    p2a_init.run()
    return TestClient(app)


def _hdr(tenant, phone=None):
    from utils import jwt_util
    return {"Authorization": f"Bearer {jwt_util.encode({'tenant_id': tenant, 'phone': phone or tenant}, 's')}"}


def _make_director_plan(c, hdr):
    """通过 /api/compose/preview 产出一条 director_plan（不调火山）。"""
    r = c.post("/api/compose/preview",
               json={"prompt": "广州美容院 抗衰精华，痛点是皱纹，产品展示，效果对比，关注我们",
                     "style": "premium", "ratio": "9:16", "duration": 30, "resolution": "1080p"},
               headers=hdr).json()
    assert r["code"] == 0, r
    return r["data"]["director_plan_id"]


def _count(table):
    from sqlalchemy import text
    s = _db.SessionLocal()
    try:
        return s.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
    finally:
        s.close()


def main():
    c = _client()
    A = _hdr("tenantA")
    B = _hdr("tenantB")

    # 防火山：任何 httpx 模块级调用即失败（TestClient 实例方法不受影响）
    import httpx
    triggered = {"n": 0}
    def _boom(*a, **k):
        triggered["n"] += 1
        raise AssertionError("P2A 不应触发火山/HTTP")
    httpx.post = httpx.get = _boom

    # ---- 1) 6 张新表存在 ----
    from sqlalchemy import inspect
    tables = set(inspect(_db.engine).get_table_names())
    for t in ["production_orders", "shot_maps", "fission_plans", "fission_variants",
              "qa_results", "skill_registry"]:
        assert t in tables, f"缺表 {t}"
    print("  ✔ 6 张新表存在")

    # ---- 2) skill_registry 12 条种子 ----
    assert _count("skill_registry") == 12, _count("skill_registry")
    print("  ✔ skill_registry 12 条种子")

    # ---- 3) skill_id 精确集合校验 ----
    from sqlalchemy import text
    s = _db.SessionLocal()
    rows = s.execute(text("SELECT skill_id, adapter FROM skill_registry")).fetchall()
    s.close()
    actual_ids = {r[0] for r in rows}
    assert actual_ids == CANONICAL, f"extra={actual_ids-CANONICAL}, missing={CANONICAL-actual_ids}"
    # 与 service 真值源也一致
    from services.skill_registry_service import CANONICAL_SKILL_IDS
    assert CANONICAL_SKILL_IDS == CANONICAL, "service 真值源与测试期望不一致"
    print("  ✔ skill_id 精确集合校验通过（12 条全等）")

    # ---- 4) adapter 全部 snake_case 且与 §2.7 一致 ----
    actual_adapters = {r[0]: r[1] for r in rows}
    assert actual_adapters == EXPECTED_ADAPTERS, actual_adapters
    import re as _re
    assert all(_re.fullmatch(r"[a-z0-9_]+_adapter", a) for a in actual_adapters.values())
    print("  ✔ adapter 全部 snake_case 且与 §2.7 完全一致")

    # ---- 5) production-orders/preview 返回 preview JSON，不入库 ----
    dp_id = _make_director_plan(c, A)
    po_before = _count("production_orders")
    sm_before = _count("shot_maps")
    # 记录 cost 基线（compose/preview 已写 estimate，这里只看 P2A preview 是否新增）
    cost_before = _count("cost_ledger") if "cost_ledger" in tables else 0
    costrec_before = _count("cost_records") if "cost_records" in tables else 0

    pv = c.post("/api/production-orders/preview",
                json={"director_plan_id": dp_id, "scenario": "product_seeding", "platform": "douyin"},
                headers=A).json()
    assert pv["code"] == 0, pv
    d = pv["data"]
    assert d["status"] == "preview" and d["production_order_id"].startswith("preview_"), d
    assert d["tenant_id"] == "tenantA" and d["ratio"] == "9:16", d
    assert d["cost_policy"]["compose_locked"] is True and d["cost_policy"]["b_track_api_cost"] == 0, d
    assert len(d["shot_maps"]) >= 1 and all(sm["tenant_id"] == "tenantA" for sm in d["shot_maps"]), d
    assert d["qa_gates"] == ["duration_check", "pts_check", "playback_validate", "md5_duplicate_check"], d
    assert _count("production_orders") == po_before and _count("shot_maps") == sm_before, "preview 不应入库"
    print("  ✔ production-orders/preview 返回 preview JSON 且不入库（shot_maps 含 tenant_id）")

    # ---- 6) production-orders POST 创建 confirmed 生产单 ----
    cr = c.post("/api/production-orders",
                json={"director_plan_id": dp_id, "scenario": "product_seeding", "platform": "douyin"},
                headers=A).json()
    assert cr["code"] == 0 and cr["data"]["status"] == "confirmed", cr
    po_id = cr["data"]["production_order_id"]
    assert po_id.startswith("po_"), po_id
    assert _count("production_orders") == po_before + 1, "create 应入库 1 条"
    print(f"  ✔ production-orders POST 创建 confirmed 生产单（{po_id}）")

    # ---- 7) production-orders/{id} 返回 order + shot_maps（含 tenant_id）----
    g = c.get(f"/api/production-orders/{po_id}", headers=A).json()
    assert g["code"] == 0 and g["data"]["production_order_id"] == po_id, g
    assert g["data"]["status"] == "confirmed" and g["data"]["director_plan_id"] == dp_id, g
    shots = g["data"]["shot_maps"]
    assert len(shots) >= 1 and all(sm["tenant_id"] == "tenantA" for sm in shots), shots
    # 租户隔离：B 看不到 A 的生产单
    assert c.get(f"/api/production-orders/{po_id}", headers=B).json()["code"] == 3001
    print("  ✔ production-orders/{id} 返回 order+shot_maps（含 tenant_id），跨租户隔离")

    # ---- 8) fission-plans/preview 返回 30 条 variant ----
    fp = c.post("/api/fission-plans/preview", json={"production_order_id": po_id}, headers=A).json()
    assert fp["code"] == 0, fp
    fpd = fp["data"]
    assert fpd["status"] == "preview" and fpd["target_count"] == 30, fpd
    assert len(fpd["variants"]) == 30, len(fpd["variants"])
    assert len(fpd["groups"]) == 6 and all(g0["count"] == 5 for g0 in fpd["groups"]), fpd["groups"]
    print("  ✔ fission-plans/preview 返回 30 条 variant（6 组×5）")

    # ---- 9) 每条 variant 有 tenant_id ----
    assert all(v["tenant_id"] == "tenantA" for v in fpd["variants"]), "variant 缺 tenant_id"
    print("  ✔ 每条 variant 含 tenant_id")

    # ---- 10) 每条 variant 的 skill_sequence 只用 12 条 canonical ----
    for v in fpd["variants"]:
        for step in v["skill_sequence"]:
            assert step["skill_id"] in CANONICAL, f"越界 skill_id: {step['skill_id']}"
        assert v["output_requirements"]["cost"] == 0
        assert v["output_requirements"]["target_seconds"] == [25, 35]
    print("  ✔ 每条 variant 的 skill_sequence 仅用 12 条 canonical skill_id（cost=0, [25,35]）")

    # fission preview 不入库
    assert _count("fission_plans") == 0 and _count("fission_variants") == 0, "fission preview 不应入库"
    print("  ✔ fission-plans/preview 不入库")

    # ---- 11) GET /api/skills 返回 12 条 ----
    sk = c.get("/api/skills", headers=A).json()
    assert sk["code"] == 0 and sk["data"]["total"] == 12, sk
    assert {it["skill_id"] for it in sk["data"]["items"]} == CANONICAL, sk
    print("  ✔ GET /api/skills 返回 12 条 canonical 技能")

    # ---- 12) skill_executor mode=execute 抛异常 ----
    from services import skill_executor
    for bad_mode in ("execute", "real", "ffmpeg"):
        try:
            skill_executor.run("safe_trim_setpts_v1", {}, mode=bad_mode)
            assert False, f"mode={bad_mode} 应抛异常"
        except ValueError:
            pass
    # 未知 skill_id 抛异常
    try:
        skill_executor.run("not_a_skill_v1", {}, mode="mock")
        assert False, "未知 skill_id 应抛异常"
    except ValueError:
        pass
    # 合法 mock / dry_validate 通过
    assert skill_executor.run("safe_trim_setpts_v1", {}, mode="mock")["status"] == "mock"
    assert skill_executor.run("safe_trim_setpts_v1", {}, mode="dry_validate")["status"] == "validated"
    print("  ✔ skill_executor：execute/real/ffmpeg 抛异常；mock/dry_validate 通过")

    # ---- 13) preview API cost=0（无新增 cost 记录）----
    cost_after = _count("cost_ledger") if "cost_ledger" in tables else 0
    costrec_after = _count("cost_records") if "cost_records" in tables else 0
    assert cost_after == cost_before, f"cost_ledger 新增 {cost_after-cost_before}"
    assert costrec_after == costrec_before, f"cost_records 新增 {costrec_after-costrec_before}"
    print("  ✔ P2A preview/create 0 成本（cost_ledger/cost_records 无新增）")

    # ---- 14) 不触发火山 ----
    assert triggered["n"] == 0, f"火山被触发 {triggered['n']} 次"
    print("  ✔ 未触发火山（httpx 陷阱 0 次）")

    # ---- 15) 不调用 remixer（skill_executor 模块未 import remixer/subprocess）----
    # 用 AST 解析「真实 import 语句」（忽略注释/文档串，避免误判安全说明文字）
    import ast
    import importlib
    src = importlib.util.find_spec("services.skill_executor").origin
    with open(src, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    banned = {"subprocess", "b_engine.remixer", "b_engine.video_composer", "a_engine.generator"}
    hit = {m for m in imported if m in banned or m.startswith("b_engine.remixer")}
    assert not hit, f"skill_executor 不得 import: {hit}"
    # 同样确认未引 videos model
    assert "models.video" not in imported and "models" not in imported, f"skill_executor 不得 import videos/models: {imported}"
    print("  ✔ skill_executor 未 import remixer/subprocess/videos（AST 校验真实 import）")

    # ---- 16) 不写 videos 表（preview/create 未新增 videos）----
    assert _count("videos") == 0, f"videos 表被写入 {_count('videos')} 条"
    print("  ✔ P2A 路径未写 videos 表")

    # ---- 17) P1.1 /b/batch-generate 回归正常 ----
    from models import Video as _V
    s = _db.SessionLocal()
    src = os.path.join(_STORAGE, "mother")
    os.makedirs(src, exist_ok=True)
    ids = []
    for _ in range(3):
        v = _V(tenant_id="tenantA", type="mother", source_type="uploaded", title="母", duration_seconds=35.0)
        s.add(v); s.commit(); ids.append(v.id)
        _mp4(os.path.join(src, f"{v.id}.mp4"))
    s.close()
    bg = c.post("/api/b/batch-generate",
                json={"prompt": "抗衰", "source_video_ids": ids, "auto_ratio": 1},
                headers=A).json()
    assert bg["code"] == 0 and bg["data"]["total_outputs"] == 3, bg
    print("  ✔ P1.1 /b/batch-generate 回归正常（3 源各 1 条，0 成本）")

    _db.engine.dispose()
    if os.path.exists("./_v4p2a_test.db"):
        os.remove("./_v4p2a_test.db")
    print("\n✅ V4 P2A ALL PASSED")


if __name__ == "__main__":
    main()
