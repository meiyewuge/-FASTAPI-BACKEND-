"""V4 P2B-A 验证：主题驱动 L2 执行计划 Dry-run（20 项验收 + 中文化 + 安全 + 开关）。

覆盖施工指令 §十一 验收要求 1-20：
2 表 migration / 不改 P2A / skill_registry 仍 12 / L2 catalog 6 / fission_plan_id=null 生成 30 /
preview 不入库 / confirm 入库 30 / 重复 confirm 幂等 / by-production-order 30 / explain 来自持久化 /
craft_explanation≥200 字 / 30 指纹唯一 dedup=1.0 / 30 theme_kernel_id 一致 / execute_allowed=false /
cost=0 / 不调火山 / 不调 remixer / 不调 ffmpeg / 不写 videos / A台B台Admin登录不退化。
另：ENABLE_L2_SKILLS 开关、tenant 隔离、幂等唯一索引。

跑法：cd backend && python tests/verify_v4_p2b_a.py
"""
import ast
import os
import subprocess
import sys
import tempfile

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
os.environ["DATABASE_URL"] = "sqlite:///./_v4p2b_test.db"

import config
import db as _db

_STORAGE = os.path.join(tempfile.mkdtemp(), "videos")
_L2_IDS = {"rhythm_edit_v1", "smooth_transition_v1", "narrative_subtitle_v1",
           "highlight_card_v1", "active_dedup_v1", "orchestration_pipeline_v1"}
_L2_ADAPTERS = {"rhythm_edit_adapter", "smooth_transition_adapter", "narrative_subtitle_adapter",
                "highlight_card_adapter", "active_dedup_adapter", "orchestration_pipeline_adapter"}


def _mp4(path):
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=1",
                    "-pix_fmt", "yuv420p", path],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _client():
    _db.engine.dispose()
    if os.path.exists("./_v4p2b_test.db"):
        os.remove("./_v4p2b_test.db")
    config.settings.auth_required = True
    config.settings.jwt_secret = "s"
    config.settings.admin_key = "K"
    config.settings.enable_compose = False
    config.settings.enable_l2_skills = False          # 默认关闭，先测开关
    config.settings.storage_dir = _STORAGE
    config.settings.storage_base_url = "https://test.local/static/videos"
    config.settings.b_remix_target_lo = 2.0           # 提速（不改 P2B 计划逻辑，仅 P1.1 回归用）
    config.settings.b_remix_target_hi = 4.0
    config.settings.b_remix_width = 320
    config.settings.b_remix_height = 240
    from fastapi.testclient import TestClient
    from main import app
    _db.init_db()
    from migrations import p2a_init, p2b_a_init
    p2a_init.run()
    mig = p2b_a_init.run()
    return TestClient(app), mig


def _hdr(tenant, phone=None):
    from utils import jwt_util
    return {"Authorization": f"Bearer {jwt_util.encode({'tenant_id': tenant, 'phone': phone or tenant}, 's')}"}


def _count(table):
    from sqlalchemy import text
    s = _db.SessionLocal()
    try:
        return s.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
    finally:
        s.close()


def _make_production_order(c, hdr):
    dp = c.post("/api/compose/preview",
                json={"prompt": "达芙荻丽修复精华，痛点皱纹暗沉松弛，产品展示质地，效果对比7天见效，品牌定格，关注领取试用装",
                      "style": "premium", "ratio": "9:16", "duration": 30, "resolution": "1080p"},
                headers=hdr).json()
    assert dp["code"] == 0, dp
    dp_id = dp["data"]["director_plan_id"]
    po = c.post("/api/production-orders",
                json={"director_plan_id": dp_id, "scenario": "product_seeding", "platform": "douyin"},
                headers=hdr).json()
    assert po["code"] == 0, po
    return po["data"]["production_order_id"]


def main():
    c, mig = _client()
    A = _hdr("tenantA")
    B = _hdr("tenantB")

    # 防火山
    import httpx
    trig = {"n": 0}
    def _boom(*a, **k):
        trig["n"] += 1
        raise AssertionError("P2B-A 不应触发火山/HTTP")
    httpx.post = httpx.get = _boom

    from sqlalchemy import inspect
    tables = set(inspect(_db.engine).get_table_names())

    # ---- 1) migration 只新增 2 张表（init_db 已预建表，故 migration 仅校验存在+索引）----
    assert "execution_plans" in tables and "skill_executions" in tables
    # 不得新增 dedup_reports 等其它表（P2B-A 只 2 张）
    assert "dedup_reports" not in tables, "P2B-A 不应新增 dedup_reports"
    assert mig["p2a_tables_present"] == ["production_orders", "shot_maps", "fission_plans",
                                         "fission_variants", "qa_results", "skill_registry"], mig
    print("  ✔ migration 只新增 2 张表（execution_plans + skill_executions），无 dedup_reports")

    # 幂等唯一索引存在
    assert "idx_ep_idempotent" in mig["execution_plans_indexes"], mig
    assert "idx_ep_tenant" in mig["execution_plans_indexes"]
    assert "idx_se_tenant" in mig["skill_executions_indexes"]
    print("  ✔ 幂等唯一索引 idx_ep_idempotent + tenant 索引就位")

    # ---- 2) 不改 P2A 表（列结构未被加 P2B 字段）----
    po_cols = {ci["name"] for ci in inspect(_db.engine).get_columns("production_orders")}
    assert "execution_plan_id" not in po_cols and "skill_chain" not in po_cols, po_cols
    for t in ["production_orders", "shot_maps", "fission_plans", "fission_variants", "qa_results", "skill_registry"]:
        assert t in tables, f"P2A 表缺失 {t}"
    print("  ✔ 不改 P2A 表（P2A 6 表完好，无 P2B 字段渗入）")

    # ---- 3) P2A skill_registry 仍 12 条 ----
    assert _count("skill_registry") == 12, _count("skill_registry")
    print("  ✔ P2A skill_registry 仍为 12 条 L1 技能")

    # ---- ENABLE_L2_SKILLS 开关：默认关闭 → 4031 ----
    po_id = _make_production_order(c, A)
    off = c.post("/api/p2b/execution-plans/preview", json={"production_order_id": po_id}, headers=A).json()
    assert off["code"] == 4031, off
    assert c.get("/api/p2b/skills", headers=A).json()["code"] == 4031
    print("  ✔ ENABLE_L2_SKILLS=false → P2B API 返回未开启（4031）")

    config.settings.enable_l2_skills = True  # staging 临时开启

    # ---- 4) P2B_L2_SKILL_CATALOG 返回 6 条 L2 ----
    sk = c.get("/api/p2b/skills", headers=A).json()
    assert sk["code"] == 0 and sk["data"]["total"] == 6, sk
    got_ids = {s["skill_id"] for s in sk["data"]["items"]}
    got_adapters = {s["adapter"] for s in sk["data"]["items"]}
    assert got_ids == _L2_IDS, got_ids
    assert got_adapters == _L2_ADAPTERS, got_adapters
    print("  ✔ /api/p2b/skills 返回 6 条 L2（canonical skill_id + snake_case adapter）")

    # theme-kernels
    tk = c.post("/api/p2b/theme-kernels", json={"production_order_id": po_id}, headers=A).json()
    assert tk["code"] == 0 and tk["data"]["theme_kernel_id"] == f"tk_{po_id}", tk
    for k in ("core_message", "emotional_hook", "main_promise", "cta_intent"):
        assert tk["data"][k], tk
    print("  ✔ theme-kernels 生成中心思想（core_message/hook/promise/cta 齐全）")

    # ---- 5) fission_plan_id=null 生成 30 条 ----
    ep_before = _count("execution_plans")
    pv = c.post("/api/p2b/execution-plans/preview",
                json={"production_order_id": po_id, "fission_plan_id": None}, headers=A).json()
    assert pv["code"] == 0 and pv["data"]["total"] == 30, pv
    plans = pv["data"]["execution_plans"]
    assert len(plans) == 30, len(plans)
    print("  ✔ fission_plan_id=null 基于生产单生成 30 条执行计划")

    # ---- 6) preview 不入库 ----
    assert _count("execution_plans") == ep_before, "preview 不应入库"
    assert _count("skill_executions") == 0, "preview 不应写 skill_executions"
    print("  ✔ preview 不入库")

    # ---- 11) craft_explanation ≥ 200 字 ----
    for p in plans:
        assert len(p["craft_explanation"]) >= 200, f"{p['execution_plan_id']} craft={len(p['craft_explanation'])}字"
    print("  ✔ 每条 craft_explanation ≥ 200 字")

    # 每条含 5 个工艺计划 + explanation
    for p in plans:
        v = p["variant_plan"]
        for key in ("rhythm_plan", "transition_plan", "subtitle_plan", "highlight_card_plan", "uniqueness_plan"):
            assert v[key] and v[key].get("explanation"), f"{p['variant_id']} 缺 {key}.explanation"
    print("  ✔ 每条含 rhythm/transition/subtitle/highlight_card/uniqueness 计划及中文说明")

    # ---- 12) 30 条参数指纹唯一 dedup_rate=1.0 ----
    dr = pv["data"]["dedup_report"]
    assert dr["unique_count"] == 30 and dr["dedup_rate"] == 1.0 and dr["duplicate_count"] == 0, dr
    fps = {p["variant_plan"]["uniqueness_plan"]["param_fingerprint"] for p in plans}
    assert len(fps) == 30, len(fps)
    print("  ✔ 30 条参数指纹唯一（dedup_rate=1.0，主动编排去重）")

    # ---- 13) 30 条 theme_kernel_id 一致 ----
    tkids = {p["variant_plan"]["theme_kernel_id"] for p in plans}
    assert tkids == {f"tk_{po_id}"}, tkids
    print("  ✔ 30 条 theme_kernel_id 一致（中心思想不跑题）")

    # ---- 14/15) execute_allowed=false & cost=0 ----
    assert pv["data"]["execute_allowed"] is False and pv["data"]["cost_estimate"] == 0
    assert all(p["execute_allowed"] is False and p["cost_estimate"] == 0 for p in plans)
    print("  ✔ execute_allowed=false 且 cost_estimate=0（只计划不执行）")

    # skill_chain 用 canonical skill_id（不是中文名）
    for p in plans:
        for step in p["skill_chain"]:
            assert "skill_id" in step and "display_name" in step, step
            assert step["skill_id"].endswith("_v1"), step
    print("  ✔ skill_chain 存 canonical skill_id + 中文 display_name")

    # ---- V1.1 硬锁①：fission_plan_id 非空校验（不存在/越权 → 3001）----
    from models import FissionPlan
    s = _db.SessionLocal()
    s.add(FissionPlan(fission_plan_id="fp_valid_A", production_order_id=po_id, tenant_id="tenantA"))
    s.add(FissionPlan(fission_plan_id="fp_other_tenant", production_order_id=po_id, tenant_id="tenantB"))
    s.commit(); s.close()
    # 合法 fission_plan_id（preview 不入库）→ 30 条且回填该 id
    okfp = c.post("/api/p2b/execution-plans/preview",
                  json={"production_order_id": po_id, "fission_plan_id": "fp_valid_A"}, headers=A).json()
    assert okfp["code"] == 0 and okfp["data"]["total"] == 30, okfp
    assert all(p["fission_plan_id"] == "fp_valid_A" for p in okfp["data"]["execution_plans"]), "应回填合法 fission_plan_id"
    # 不存在的 fission_plan_id → 3001
    assert c.post("/api/p2b/execution-plans/preview",
                  json={"production_order_id": po_id, "fission_plan_id": "fp_not_exist"}, headers=A).json()["code"] == 3001
    # 属于其它租户的 fission_plan_id（A 请求 B 的）→ 3001
    assert c.post("/api/p2b/execution-plans/preview",
                  json={"production_order_id": po_id, "fission_plan_id": "fp_other_tenant"}, headers=A).json()["code"] == 3001
    # confirm 非法 fission_plan_id → 3001 且不写入
    assert c.post("/api/p2b/execution-plans",
                  json={"production_order_id": po_id, "fission_plan_id": "fp_not_exist"}, headers=A).json()["code"] == 3001
    assert _count("execution_plans") == 0, "非法 fission confirm 不应写入"
    print("  ✔ V1.1 硬锁①：fission_plan_id 非空校验（不存在/越权→3001，未校验不写入）")

    # ---- 7) confirm 入库 30 条 ----
    cf = c.post("/api/p2b/execution-plans", json={"production_order_id": po_id}, headers=A).json()
    assert cf["code"] == 0 and cf["data"]["total"] == 30 and cf["data"]["idempotent"] is False, cf
    assert cf["data"]["status"] == "confirmed", cf
    assert _count("execution_plans") == 30, _count("execution_plans")
    assert _count("skill_executions") == 30 * 7, _count("skill_executions")
    print("  ✔ confirm 入库 30 条 execution_plans + 210 条 skill_executions（status=planned）")

    # skill_executions 全 planned
    from sqlalchemy import text
    s = _db.SessionLocal()
    statuses = {r[0] for r in s.execute(text("SELECT DISTINCT status FROM skill_executions")).fetchall()}
    s.close()
    assert statuses == {"planned"}, statuses
    print("  ✔ skill_executions 全部 status=planned（不执行）")

    # ---- 8) 重复 confirm 幂等 ----
    cf2 = c.post("/api/p2b/execution-plans", json={"production_order_id": po_id}, headers=A).json()
    assert cf2["code"] == 0 and cf2["data"]["idempotent"] is True, cf2
    assert _count("execution_plans") == 30, "重复 confirm 不应新增"
    assert set(cf2["data"]["execution_plan_ids"]) == set(cf["data"]["execution_plan_ids"])
    print("  ✔ 重复 confirm 幂等（仍 30 条，不重复生成）")

    # ---- 9) by-production-order 返回 30 ----
    bypo = c.get(f"/api/p2b/execution-plans/by-production-order/{po_id}", headers=A).json()
    assert bypo["code"] == 0 and bypo["data"]["total"] == 30, bypo
    assert all(it["variant_plan_json"] for it in bypo["data"]["execution_plans"]), "应含 variant_plan_json"
    print("  ✔ by-production-order 返回 30 条已确认计划（含 variant_plan_json）")

    # ---- 10) explain 来自持久化 JSON ----
    one_id = cf["data"]["execution_plan_ids"][0]
    ex = c.get(f"/api/p2b/execution-plans/{one_id}/explain", headers=A).json()
    assert ex["code"] == 0, ex
    for k in ("craft_explanation", "rhythm_explanation", "transition_explanation",
              "subtitle_explanation", "highlight_card_explanation", "uniqueness_explanation"):
        assert ex["data"][k], f"explain 缺 {k}"
    # 直接对比 DB 持久化字段，确认来自持久化而非内存
    import json as _json
    s = _db.SessionLocal()
    row = s.execute(text("SELECT variant_plan_json FROM execution_plans WHERE execution_plan_id=:i"),
                    {"i": one_id}).fetchone()
    s.close()
    vp = _json.loads(row[0])
    assert ex["data"]["rhythm_explanation"] == vp["rhythm_plan"]["explanation"]
    print("  ✔ explain 字段来自持久化 variant_plan_json（非临时内存）")

    # get 详情
    g = c.get(f"/api/p2b/execution-plans/{one_id}", headers=A).json()
    assert g["code"] == 0 and g["data"]["execution_plan_id"] == one_id
    assert g["data"]["variant_plan"]["rhythm_plan"]["explanation"], g
    print("  ✔ get 详情含完整 variant_plan JSON")

    # tenant 隔离：B 看不到 A 的计划
    assert c.get(f"/api/p2b/execution-plans/{one_id}", headers=B).json()["code"] == 3001
    assert c.get(f"/api/p2b/execution-plans/by-production-order/{po_id}", headers=B).json()["data"]["total"] == 0
    assert c.post("/api/p2b/execution-plans/preview", json={"production_order_id": po_id}, headers=B).json()["code"] == 3001
    print("  ✔ tenant 隔离：B 无法访问 A 的生产单/执行计划")

    # ---- V1.1 硬锁①续：合法 fission_plan_id 正常写入（独立生产单）----
    po_f = _make_production_order(c, A)
    s = _db.SessionLocal()
    s.add(FissionPlan(fission_plan_id="fp_for_pf", production_order_id=po_f, tenant_id="tenantA"))
    s.commit(); s.close()
    cf_f = c.post("/api/p2b/execution-plans",
                  json={"production_order_id": po_f, "fission_plan_id": "fp_for_pf"}, headers=A).json()
    assert cf_f["code"] == 0 and cf_f["data"]["total"] == 30, cf_f
    s = _db.SessionLocal()
    fids = {r[0] for r in s.execute(
        text("SELECT DISTINCT fission_plan_id FROM execution_plans WHERE production_order_id=:p"),
        {"p": po_f}).fetchall()}
    s.close()
    assert fids == {"fp_for_pf"}, fids
    print("  ✔ V1.1 硬锁①：合法 fission_plan_id 正常写入 execution_plans")

    # ---- V1.1 硬锁②：production 环境硬拦截（无视 ENABLE_L2_SKILLS）----
    _orig_env = config.settings.app_env
    try:
        config.settings.enable_l2_skills = True
        for env in ("production", "prod"):
            config.settings.app_env = env
            assert c.get("/api/p2b/skills", headers=A).json()["code"] == 4031, f"{env}+true 应 4031"
            assert c.post("/api/p2b/execution-plans/preview",
                          json={"production_order_id": po_id}, headers=A).json()["code"] == 4031
        # production + ENABLE_L2_SKILLS=false → 仍 4031
        config.settings.app_env = "production"; config.settings.enable_l2_skills = False
        assert c.get("/api/p2b/skills", headers=A).json()["code"] == 4031
        # staging/dev + true → 可用
        config.settings.enable_l2_skills = True
        for env in ("staging", "dev"):
            config.settings.app_env = env
            assert c.get("/api/p2b/skills", headers=A).json()["code"] == 0, f"{env}+true 应可用"
    finally:
        config.settings.app_env = _orig_env
        config.settings.enable_l2_skills = True
    print("  ✔ V1.1 硬锁②：production/prod 环境硬拦截（即使 ENABLE_L2_SKILLS=true 仍返回 4031）")

    # ---- 16) 不调火山 ----
    assert trig["n"] == 0, f"火山被触发 {trig['n']} 次"
    print("  ✔ 不调火山（httpx 陷阱 0 次）")

    # ---- 17/18) 不调 remixer / ffmpeg（AST 校验 P2B 服务真实 import）----
    banned = {"subprocess", "b_engine.remixer", "b_engine.video_composer", "a_engine.generator"}
    p2b_files = ["services/p2b_l2_skills.py", "services/p2b_theme_service.py",
                 "services/p2b_orchestration_service.py", "services/p2b_execution_plan_service.py",
                 "services/p2b_skill_catalog.py", "api/p2b_routes.py"]
    for fp in p2b_files:
        tree = ast.parse(open(os.path.join(_BACKEND, fp), encoding="utf-8").read())
        imps = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                imps |= {a.name for a in n.names}
            if isinstance(n, ast.ImportFrom):
                imps.add(n.module or "")
        hit = {m for m in imps if m in banned or m.startswith("b_engine.remixer")}
        assert not hit, f"{fp} 不得 import {hit}"
    print("  ✔ P2B 全部服务未 import remixer/ffmpeg/subprocess（AST 校验）")

    # ---- 19) 不写 videos ----
    assert _count("videos") == 0, f"videos 被写 {_count('videos')} 条"
    print("  ✔ P2B-A 未写 videos 表")

    # ---- 20) A台/B台/Admin/登录/partial_done 不退化 ----
    # 登录 + bootstrap + /api/me
    code = c.post("/api/admin/invite/generate", json={"count": 1}, headers={"X-Admin-Key": "K"}).json()["data"]["items"][0]["code"]
    c.post("/api/admin/bootstrap", json={"phone": "13800000001"}, headers={"X-Admin-Key": "K"})
    login = c.post("/api/auth/login", json={"phone": "13800000001", "invite_code": code}).json()["data"]
    assert login["role"] == "super_admin", login
    meh = {"Authorization": f"Bearer {login['token']}"}
    assert c.get("/api/me", headers=meh).json()["data"]["is_admin"] is True
    # A台防误触仍在
    assert c.post("/api/generate", json={"text": "帮我做100个抗衰视频"}, headers=A).json()["code"] == 2001
    # B台批量裂变仍可（3 源 → partial 正常）
    from models import Video as _V
    s = _db.SessionLocal()
    src = os.path.join(_STORAGE, "mother"); os.makedirs(src, exist_ok=True)
    ids = []
    for _ in range(3):
        v = _V(tenant_id="tenantA", type="mother", source_type="uploaded", title="母", duration_seconds=35.0)
        s.add(v); s.commit(); ids.append(v.id); _mp4(os.path.join(src, f"{v.id}.mp4"))
    s.close()
    bg = c.post("/api/b/batch-generate", json={"prompt": "抗衰", "source_video_ids": ids, "auto_ratio": 1}, headers=A).json()
    assert bg["code"] == 0 and bg["data"]["total_outputs"] == 3, bg
    print("  ✔ A台/B台/Admin/登录/partial_done 不退化")

    # P2A skill_registry 在 P2B 运行后仍 12 条（不写入 L2）
    assert _count("skill_registry") == 12, _count("skill_registry")
    print("  ✔ 运行 P2B 后 P2A skill_registry 仍 12 条（L2 未写入注册表）")

    _db.engine.dispose()
    if os.path.exists("./_v4p2b_test.db"):
        os.remove("./_v4p2b_test.db")
    print("\n✅ V4 P2B-A ALL PASSED")


if __name__ == "__main__":
    main()
