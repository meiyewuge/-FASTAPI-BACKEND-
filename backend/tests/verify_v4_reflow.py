"""V4 P0 业务资产回流层验证。

覆盖（对应吴哥要求）：
1. B台批量任务生成 workflow_run（含 output/cost 回填）
2. 下载视频生成 video_feedback_signal（/api/events/track）
3. favorite 生成 video_feedback_signal
4. feedback 生成 knowledge_candidate（pending）
5. 普通 user 不能访问候选池管理（403）
6. super_admin 可查看候选池
7. approve/reject 状态流转正常
8. 多租户隔离正常（A 的 track/feedback 不串到 B；B 不能对 A 的视频反馈）
"""
import os
import subprocess
import sys
import tempfile

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
os.environ["DATABASE_URL"] = "sqlite:///./_v4reflow_test.db"

import config
import db as _db

_STORAGE = os.path.join(tempfile.mkdtemp(), "videos")


def _mp4(path):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=1",
         "-pix_fmt", "yuv420p", path],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _client():
    _db.engine.dispose()
    if os.path.exists("./_v4reflow_test.db"):
        os.remove("./_v4reflow_test.db")
    config.settings.auth_required = True
    config.settings.jwt_secret = "s"
    config.settings.admin_key = "K"
    config.settings.storage_dir = _STORAGE
    config.settings.storage_base_url = "https://test.local/static/videos"
    from fastapi.testclient import TestClient
    from main import app
    _db.init_db()
    return TestClient(app)


def _hdr(tenant, phone):
    from utils import jwt_util
    return {"Authorization": f"Bearer {jwt_util.encode({'tenant_id': tenant, 'phone': phone}, 's')}"}


def _make_mother(tenant, title="母"):
    """直接建一条本地母视频，返回 video_id。"""
    from models import Video
    s = _db.SessionLocal()
    v = Video(tenant_id=tenant, type="mother", source_type="uploaded", title=title,
              duration_seconds=35.0)   # P1：合格源需 ≥30s
    s.add(v); s.commit(); vid = v.id; s.close()
    os.makedirs(os.path.join(_STORAGE, "mother"), exist_ok=True)
    _mp4(os.path.join(_STORAGE, "mother", f"{vid}.mp4"))
    return vid


def main():
    c = _client()
    A = _hdr("tenantA", "13800000001")
    B = _hdr("tenantB", "13900000002")

    # ---- 1) B台批量任务生成 workflow_run ----
    m1 = _make_mother("tenantA")
    m2 = _make_mother("tenantA")
    m3 = _make_mother("tenantA")
    r = c.post("/api/b/batch-generate",
               json={"prompt": "抗衰", "source_video_ids": [m1, m2, m3], "auto_ratio": 1},
               headers=A).json()["data"]
    batch_id = r["batch_id"]
    from models import WorkflowRun, VideoFeedbackSignal, KnowledgeCandidate
    s = _db.SessionLocal()
    runs = s.query(WorkflowRun).filter(WorkflowRun.tenant_id == "tenantA", WorkflowRun.mode == "batch").all()
    assert len(runs) == 1, runs
    run = runs[0]
    assert run.status == "done", run.status
    assert run.output_video_count == 3, run.output_video_count
    assert run.cost_amount == 0, run.cost_amount       # B台 0 成本
    assert run.source_video_count == 3, run.source_video_count
    s.close()
    print(f"  ✔ B台批量任务生成 workflow_run（output=3, cost=0, status=done）")

    # 取一条裂变视频做行为/反馈
    vl = c.get("/api/videos", params={"type": "viral", "batch_id": batch_id}, headers=A).json()["data"]
    vid = vl["items"][0]["video_id"]

    # ---- 2) 下载视频生成 video_feedback_signal ----
    assert c.post("/api/events/track", json={"action": "download", "video_id": vid}, headers=A).json()["code"] == 0
    # ---- 3) favorite 生成 video_feedback_signal ----
    assert c.post("/api/events/track", json={"action": "favorite", "video_id": vid}, headers=A).json()["code"] == 0
    s = _db.SessionLocal()
    sigs = s.query(VideoFeedbackSignal).filter(VideoFeedbackSignal.tenant_id == "tenantA").all()
    actions = {x.action for x in sigs}
    assert "download" in actions and "favorite" in actions, actions
    s.close()
    print("  ✔ download / favorite 生成 video_feedback_signal")

    # 非法 action 拒绝
    assert c.post("/api/events/track", json={"action": "hack", "video_id": vid}, headers=A).json()["code"] == 2001
    print("  ✔ 非法 action 被拒（2001）")

    # ---- 4) feedback 生成 knowledge_candidate（pending）----
    fb = c.post(f"/api/videos/{vid}/feedback",
                json={"rating": "good", "tags": ["适合获客", "钩子好"], "note": "适合发小红书"},
                headers=A).json()
    assert fb["code"] == 0 and fb["data"]["status"] == "pending", fb
    cand_id = fb["data"]["candidate_id"]
    print("  ✔ feedback 生成 knowledge_candidate（pending）")

    # ---- 5) 普通 user 不能访问候选池管理 ----
    # tenantA 当前 JWT role=user（未 bootstrap）
    assert c.get("/api/admin/knowledge-candidates", headers=A).status_code == 403
    print("  ✔ 普通 user 访问候选池管理 → 403")

    # ---- 6) super_admin 可查看候选池 ----
    code = c.post("/api/admin/invite/generate", json={"count": 1}, headers={"X-Admin-Key": "K"}).json()["data"]["items"][0]["code"]
    c.post("/api/admin/bootstrap", json={"phone": "13800000001"}, headers={"X-Admin-Key": "K"})
    login = c.post("/api/auth/login", json={"phone": "13800000001", "invite_code": code}).json()["data"]
    assert login["role"] == "super_admin", login
    SA = {"Authorization": f"Bearer {login['token']}"}
    lst = c.get("/api/admin/knowledge-candidates", headers=SA).json()["data"]
    assert lst["total"] >= 1 and any(it["id"] == cand_id for it in lst["items"]), lst
    print("  ✔ super_admin 可查看候选池")

    # ---- 7) approve/reject 状态流转 ----
    ap = c.post(f"/api/admin/knowledge-candidates/{cand_id}/approve", json={"note": "入库"}, headers=SA).json()
    assert ap["code"] == 0 and ap["data"]["status"] == "approved" and ap["data"]["reviewed_by"] == "13800000001", ap
    # 再加一条候选并 reject
    fb2 = c.post(f"/api/videos/{vid}/feedback", json={"rating": "bad", "note": "节奏太慢"}, headers=A).json()["data"]
    rj = c.post(f"/api/admin/knowledge-candidates/{fb2['candidate_id']}/reject", json={"note": "不合适"}, headers=SA).json()
    assert rj["code"] == 0 and rj["data"]["status"] == "rejected", rj
    pend = c.get("/api/admin/knowledge-candidates", params={"status": "pending"}, headers=SA).json()["data"]
    assert all(it["status"] == "pending" for it in pend["items"]), pend
    print("  ✔ approve/reject 状态流转正常（含 status 过滤）")

    # ---- 8) 多租户隔离 ----
    # B 不能对 A 的视频反馈/埋点
    assert c.post(f"/api/videos/{vid}/feedback", json={"rating": "good"}, headers=B).json()["code"] == 2001
    assert c.post("/api/events/track", json={"action": "play", "video_id": vid}, headers=B).json()["code"] == 2001
    # B 自己的回流数据独立（此处 B 无数据）
    s = _db.SessionLocal()
    b_runs = s.query(WorkflowRun).filter(WorkflowRun.tenant_id == "tenantB").count()
    b_sigs = s.query(VideoFeedbackSignal).filter(VideoFeedbackSignal.tenant_id == "tenantB").count()
    a_cands = s.query(KnowledgeCandidate).filter(KnowledgeCandidate.tenant_id == "tenantA").count()
    b_cands = s.query(KnowledgeCandidate).filter(KnowledgeCandidate.tenant_id == "tenantB").count()
    s.close()
    assert b_runs == 0 and b_sigs == 0 and a_cands >= 2 and b_cands == 0, (b_runs, b_sigs, a_cands, b_cands)
    print("  ✔ 多租户隔离正常（B 不能反馈 A 的视频；回流数据按租户隔离）")

    _db.engine.dispose()
    if os.path.exists("./_v4reflow_test.db"):
        os.remove("./_v4reflow_test.db")
    print("\n✅ V4 P0 业务资产回流层 ALL PASSED")


if __name__ == "__main__":
    main()
