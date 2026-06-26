"""业务资产回流层服务（V4 P0 预留）。

记录工作流过程、视频行为信号；用户反馈沉淀为知识候选池（pending）。
**不默认把 mp4/Word全文/压缩包内容写入大库**，仅记录过程与脱敏摘要，审核后才进大库。
所有写入的 tenant_id / phone 均来自 JWT，不信任前端。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from models import CostRecord, KnowledgeCandidate, Task, Video, VideoFeedbackSignal, WorkflowRun

ALLOWED_ACTIONS = {
    "play", "select", "send_to_b", "download", "export", "favorite", "dislike", "delete",
}

_SUMMARY_MAX = 500  # 候选池摘要长度上限（避免内联大段原文）


# ---------------- 工作流记录 ----------------
def start_run(db: Session, tenant_id: str, phone: str | None, mode: str, prompt: str | None,
              *, input_image_count: int = 0, input_file_count: int = 0,
              input_video_count: int = 0, input_text_length: int = 0,
              source_video_count: int = 0) -> str:
    run = WorkflowRun(
        run_id=uuid.uuid4().hex,
        tenant_id=tenant_id,
        phone=phone,
        prompt=(prompt or "")[:2000],
        mode=mode,
        input_image_count=input_image_count,
        input_file_count=input_file_count,
        input_video_count=input_video_count,
        input_text_length=input_text_length,
        source_video_count=source_video_count,
        status="running",
    )
    db.add(run)
    db.commit()
    return run.run_id


def finalize_for_task(db: Session, task_id: str) -> None:
    """任务结束后回填其 run（按同 run_id 的全部 task 聚合 output/cost/status）。"""
    task = db.get(Task, task_id)
    if task is None or not task.run_id:
        return
    run = db.get(WorkflowRun, task.run_id)
    if run is None:
        return
    sibs = db.query(Task).filter(Task.run_id == task.run_id).all()
    statuses = [t.status for t in sibs]
    outputs = 0
    for t in sibs:
        if t.status == "done" and t.result:
            try:
                outputs += len(json.loads(t.result).get("videos", []))
            except Exception:  # noqa: BLE001
                pass
    sib_ids = [t.id for t in sibs]
    cost = (
        db.query(CostRecord)
        .with_entities(CostRecord.amount)
        .filter(CostRecord.task_id.in_(sib_ids))
        .all()
    )
    cost_amount = float(sum((c[0] or 0.0) for c in cost))
    errors = [t.error for t in sibs if t.status == "failed" and t.error]

    run.output_video_count = outputs
    run.cost_amount = cost_amount
    if all(s in ("done", "failed") for s in statuses):
        run.status = "failed" if all(s == "failed" for s in statuses) else "done"
        run.completed_at = datetime.utcnow()
        run.error_message = "; ".join(errors)[:1000] if errors else None
    else:
        run.status = "running"
    db.commit()


# ---------------- 行为信号 ----------------
def track_event(db: Session, tenant_id: str, phone: str | None, action: str,
                video_id: int | None = None, context: dict | None = None) -> VideoFeedbackSignal:
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"不支持的 action：{action}")
    # video 归属校验（若给了 video_id）
    if video_id is not None:
        v = db.query(Video).filter(Video.id == video_id, Video.tenant_id == tenant_id).first()
        if v is None:
            raise ValueError("视频不存在或不属于该租户")
    sig = VideoFeedbackSignal(
        tenant_id=tenant_id, phone=phone, video_id=video_id, action=action,
        context=json.dumps(context, ensure_ascii=False) if context else None,
    )
    db.add(sig)
    db.commit()
    return sig


# ---------------- 反馈 → 候选池 ----------------
def submit_feedback(db: Session, tenant_id: str, phone: str | None, video_id: int,
                    rating: str, tags: list[str] | None, note: str | None) -> dict:
    v = db.query(Video).filter(Video.id == video_id, Video.tenant_id == tenant_id).first()
    if v is None:
        raise ValueError("视频不存在或不属于该租户")
    if rating not in ("good", "bad", "favorite"):
        raise ValueError("rating 必须为 good / bad / favorite")

    # 行为信号
    sig = VideoFeedbackSignal(
        tenant_id=tenant_id, phone=phone, video_id=video_id,
        action="favorite" if rating in ("good", "favorite") else "dislike",
        context=json.dumps({"rating": rating, "tags": tags or []}, ensure_ascii=False),
    )
    db.add(sig)

    # 候选池（pending；仅脱敏摘要，不内联原文）
    cand = KnowledgeCandidate(
        tenant_id=tenant_id, phone=phone,
        source_module="video_v4", source_type="user_feedback",
        video_id=video_id, batch_id=v.batch_id,
        title=v.title,
        content_summary=(note or "")[:_SUMMARY_MAX],
        tags=json.dumps(tags or [], ensure_ascii=False),
        raw_ref=f"video:{video_id}",
        risk_level="low",
        status="pending",
    )
    db.add(cand)
    db.commit()
    return {"signal_id": sig.id, "candidate_id": cand.id, "status": "pending"}


# ---------------- 候选池管理（super_admin）----------------
def list_candidates(db: Session, status: str | None = None, limit: int = 100) -> list[dict]:
    q = db.query(KnowledgeCandidate)
    if status:
        q = q.filter(KnowledgeCandidate.status == status)
    rows = q.order_by(KnowledgeCandidate.created_at.desc()).limit(limit).all()
    return [_cand_brief(r) for r in rows]


def review_candidate(db: Session, candidate_id: int, decision: str,
                     reviewer_phone: str | None, note: str | None = None) -> dict | None:
    if decision not in ("approved", "rejected"):
        raise ValueError("decision 必须为 approved 或 rejected")
    c = db.get(KnowledgeCandidate, candidate_id)
    if c is None:
        return None
    c.status = decision
    c.reviewed_at = datetime.utcnow()
    c.reviewed_by = reviewer_phone
    if note is not None:
        c.review_note = note[:255]
    db.commit()
    return _cand_brief(c)


def _cand_brief(c: KnowledgeCandidate) -> dict:
    return {
        "id": c.id,
        "tenant_id": c.tenant_id,
        "phone": c.phone,
        "source_module": c.source_module,
        "source_type": c.source_type,
        "video_id": c.video_id,
        "batch_id": c.batch_id,
        "title": c.title,
        "content_summary": c.content_summary,
        "tags": json.loads(c.tags) if c.tags else [],
        "raw_ref": c.raw_ref,
        "risk_level": c.risk_level,
        "status": c.status,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "reviewed_at": c.reviewed_at.isoformat() if c.reviewed_at else None,
        "reviewed_by": c.reviewed_by,
        "review_note": c.review_note,
    }
