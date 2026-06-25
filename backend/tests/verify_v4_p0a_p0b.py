"""V4 P0-A 安全止血 + P0-B Director-Prompt Engine 验证（16 点）。

不触发真实火山、不启用真实 compose、不大文件压测。
"""
import os
import sys
import tempfile

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
os.environ["DATABASE_URL"] = "sqlite:///./_v4p0ab_test.db"

import config
import db as _db

_UPLOAD = os.path.join(tempfile.mkdtemp(), "uploads")
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360000002000100ffff03000006000557bfabd40000000049454e44ae426082"
)


def _client():
    _db.engine.dispose()
    if os.path.exists("./_v4p0ab_test.db"):
        os.remove("./_v4p0ab_test.db")
    config.settings.auth_required = True
    config.settings.jwt_secret = "s"
    config.settings.admin_key = "K"
    config.settings.enable_compose = False
    config.settings.upload_dir = _UPLOAD
    config.settings.upload_base_url = "https://video.test/static/uploads"
    from fastapi.testclient import TestClient
    from main import app
    _db.init_db()
    return TestClient(app)


def _hdr(tenant="t1", phone="13800000000"):
    from utils import jwt_util
    return {"Authorization": f"Bearer {jwt_util.encode({'tenant_id': tenant, 'phone': phone}, 's')}"}


def _upload_image(c, hdr, n=3):
    files = [("files", (f"img{i}.png", _PNG, "image/png")) for i in range(n)]
    r = c.post("/api/uploads/batch", files=files, headers=hdr).json()["data"]
    return [u["file_id"] for u in r["uploaded"]]


def main():
    import httpx
    c = _client()
    A = _hdr()

    # 防火山被调：preview 路径若误调 httpx 立即报错
    _orig_post, _orig_get = httpx.post, httpx.get
    def _boom(*a, **k): raise AssertionError("preview 不应调用火山 API")
    httpx.post = _boom; httpx.get = _boom

    # 价格 BUG-2：1080p 15s = 2.48*15 = 37.20
    from cost_engine.pricing_model import estimate_cost
    assert estimate_cost("video.generate.a", 15, "1080p") == 37.20, estimate_cost("video.generate.a", 15, "1080p")
    print("  ✔ BUG-2 定价修正：1080p 15s = ¥37.20")

    img_ids = _upload_image(c, A, 3)

    # 1-6) preview：不调火山 / 不扣费 / 返回 director_plan / T1-T5 / 图片 role
    pr = c.post("/api/compose/preview",
                json={"prompt": "达芙荻丽奢华油，夏季干皮上妆卡粉救星，99%天然植萃",
                      "image_file_ids": img_ids, "style": "premium", "duration": 15, "resolution": "1080p"},
                headers=A).json()
    assert pr["code"] == 0, pr
    data = pr["data"]
    print("  ✔ preview 未调用火山（httpx 已设陷阱，未触发）")

    from models import CostLedger
    s = _db.SessionLocal()
    events = {x.event_type for x in s.query(CostLedger).filter(CostLedger.tenant_id == "t1").all()}
    s.close()
    assert events == {"estimate"}, events  # 仅预估，无 precharge
    print("  ✔ preview 不扣费（仅 estimate 流水，无 precharge）")

    assert data["director_plan_id"] and data["director_plan"]["storyboard"], data
    print("  ✔ preview 返回 director_plan（含分镜）")

    text = data["seedance_text_prompt"]
    for tag in ("【T1-", "【T2-", "【T3-", "【T4-", "【T5-"):
        assert tag in text, (tag, text[:200])
    assert data["director_plan"]["versions"]["director_prompt_version"] == "director_prompt_v1"
    print("  ✔ preview 返回 T1-T5 结构化提示词 + 模板版本")

    roles = data["image_roles"]
    assert roles[0]["role"] == "first_frame", roles
    assert all(r["role"] == "reference_image" for r in roles[1:]), roles
    assert all(r["url"].startswith("https://") for r in roles), roles
    print("  ✔ 图片 role：第1张 first_frame，第2-9张 reference_image（HTTPS）")

    # estimated_cost = 37.20；generate_audio 可配置
    assert data["estimated_cost"] == 37.20 and data["generate_audio"] is True, data
    # content[] 含 image_url role
    img_content = [x for x in data["seedance_content"] if x["type"] == "image_url"]
    assert len(img_content) == 3 and img_content[0]["role"] == "first_frame", data["seedance_content"]
    print("  ✔ image_file_ids 进入 content[]；generate_audio=True 可配置；费用预估=37.20")

    # 7) 图片不可访问 → 清晰错误
    r = c.post("/api/compose/preview",
               json={"prompt": "测试", "image_file_ids": ["nonexistent_fid"], "duration": 15},
               headers=A).json()
    assert r["code"] == 2002 and "图片无法被视频模型访问" in r["message"], r
    print("  ✔ 图片不可访问 → 2002「图片无法被视频模型访问，请重新上传或等待处理完成。」")

    # 8) ENABLE_COMPOSE=false 拒绝
    r = c.post("/api/compose",
               json={"prompt": "x", "total_seconds": 15, "confirmed_cost": True,
                     "director_plan_id": data["director_plan_id"]},
               headers=A).json()
    assert r["code"] == 4031 and "生成通道维护中" in r["message"], r
    print("  ✔ ENABLE_COMPOSE=false → 4031「生成通道维护中，暂不可用。」")

    # 9/10) 解锁后：未 confirmed_cost 拒绝；无 plan 无 prompt 拒绝；有 plan+confirmed 放行（不真跑）
    config.settings.enable_compose = True
    import api.routes as routes
    captured = []
    routes.dispatch_compose = lambda tid: captured.append(tid)   # 拦截，不真跑 compose

    r = c.post("/api/compose", json={"director_plan_id": data["director_plan_id"], "total_seconds": 15,
                                     "confirmed_cost": False}, headers=A).json()
    assert r["code"] == 2001 and "确认生成费用" in r["message"], r
    print("  ✔ 未 confirmed_cost → 拒绝")

    r = c.post("/api/compose", json={"confirmed_cost": True, "total_seconds": 15}, headers=A).json()
    assert r["code"] == 2001, r   # 无 director_plan_id 且无 prompt
    print("  ✔ 无 director_plan 且无 prompt → 拒绝")

    r = c.post("/api/compose", json={"director_plan_id": data["director_plan_id"], "total_seconds": 15,
                                     "confirmed_cost": True}, headers=A).json()
    assert r["code"] == 0 and r["data"]["task_id"] and captured, r
    print("  ✔ 有 director_plan + confirmed_cost → 放行（dispatch 已拦截，不真跑火山）")
    config.settings.enable_compose = False

    # 11) submit 成功后立即 precharge（ledger 单元）
    from cost_engine import cost_ledger
    s = _db.SessionLocal()
    amt = cost_ledger.precharge(s, "t1", "task_X", "job_X", "compose", 15, "1080p")
    assert amt == 37.20, amt
    dup = cost_ledger.precharge(s, "t1", "task_X", "job_X", "compose", 15, "1080p")
    assert dup == 0.0, dup   # 不重复预扣
    s.commit(); s.close()
    print("  ✔ precharge 立即扣费=37.20；重复 precharge 去重=0（recovery 不重复扣）")

    # 12) failed 自动 refund
    from tasks.runner import execute_task
    from tasks import video_task
    s = _db.SessionLocal()
    t = video_task.create_task(s, "t1", "compose", {"prompt": "x", "total_seconds": 15})
    tid = t.id
    cost_ledger.precharge(s, "t1", tid, "job_Y", "compose", 15, "1080p")
    s.commit(); s.close()
    execute_task(tid)   # enable_compose=False → compose_service.run raises → failed → refund
    s = _db.SessionLocal()
    rows = s.query(CostLedger).filter(CostLedger.task_id == tid).all()
    types = {r.event_type for r in rows}
    refunded = sum(r.actual_amount or 0 for r in rows if r.event_type == "refund")
    s.close()
    assert "refund" in types and refunded == -37.20, (types, refunded)
    print("  ✔ 任务 failed → 自动 refund（退回 ¥37.20）")

    # 13) recovery 不重复 submit compose（ENABLE_COMPOSE=false 跳过）
    s = _db.SessionLocal()
    ct = video_task.create_task(s, "t1", "compose", {"prompt": "y", "total_seconds": 15})
    s.commit(); cid = ct.id; s.close()
    from tasks import recovery
    recovered = recovery.recover()
    assert cid not in recovered, recovered   # compose 被跳过
    s = _db.SessionLocal()
    assert s.get(__import__("models").Task, cid).status == "pending"   # 仍 pending，未执行
    assert not s.query(CostLedger).filter(CostLedger.task_id == cid, CostLedger.event_type == "precharge").first()
    s.close()
    print("  ✔ recovery 跳过 compose（锁未开）→ 不重复 submit、不预扣")

    # 14) provider_job_id 持久化
    s = _db.SessionLocal()
    from models import Task
    tt = s.get(Task, tid)
    tt.provider_job_id = "job_persist_1"; s.commit(); s.close()
    s = _db.SessionLocal()
    assert s.get(Task, tid).provider_job_id == "job_persist_1"
    s.close()
    print("  ✔ provider_job_id 持久化（Task.provider_job_id 列）")

    # 15) Patch6 权限不受影响
    code = c.post("/api/admin/invite/generate", json={"count": 1}, headers={"X-Admin-Key": "K"}).json()["data"]["items"][0]["code"]
    c.post("/api/admin/bootstrap", json={"phone": "13700000000"}, headers={"X-Admin-Key": "K"})
    login = c.post("/api/auth/login", json={"phone": "13700000000", "invite_code": code}).json()["data"]
    assert login["role"] == "super_admin", login
    print("  ✔ Patch6 管理员权限不受影响")

    httpx.post, httpx.get = _orig_post, _orig_get
    _db.engine.dispose()
    if os.path.exists("./_v4p0ab_test.db"):
        os.remove("./_v4p0ab_test.db")
    print("\n✅ V4 P0-A + P0-B ALL PASSED")


if __name__ == "__main__":
    main()
