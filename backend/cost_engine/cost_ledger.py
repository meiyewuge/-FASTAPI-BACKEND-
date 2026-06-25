"""成本流水台账服务（V4 P0-A，BUG-2）。

事件流水：estimate / precharge / refund / final_adjust。
- 提交火山成功拿到 provider_job_id 后立即 precharge（不等完成），杜绝暗烧。
- failed/cancelled 自动 refund。
- recovery 不得重复 precharge：以 (task_id, provider_job_id) 去重。
价格一律走 pricing_model，不在此散落硬编码。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from cost_engine.pricing_model import estimate_cost
from models import CostLedger


def _add(db: Session, **kw) -> CostLedger:
    row = CostLedger(**kw)
    db.add(row)
    db.flush()
    return row


def estimate(db: Session, tenant_id: str, request_type: str, duration: float,
             resolution: str = "1080p", model: str | None = None,
             user_phone: str | None = None, task_id: str | None = None) -> float:
    """预估金额（preview 用），写一条 estimate 流水，返回金额。"""
    api = "video.generate.a" if request_type in ("compose", "a_generate") else "video.remix.b"
    amount = estimate_cost(api, duration, resolution)
    _add(db, task_id=task_id, tenant_id=tenant_id, user_phone=user_phone, model=model,
         resolution=resolution, duration_seconds=duration, request_type=request_type,
         estimated_amount=amount, event_type="estimate", status="ok")
    return amount


def already_precharged(db: Session, task_id: str, provider_job_id: str | None) -> bool:
    q = db.query(CostLedger).filter(CostLedger.task_id == task_id,
                                    CostLedger.event_type == "precharge")
    if provider_job_id:
        q = q.filter(CostLedger.provider_job_id == provider_job_id)
    return q.first() is not None


def precharge(db: Session, tenant_id: str, task_id: str, provider_job_id: str,
              request_type: str, duration: float, resolution: str = "1080p",
              model: str | None = None, user_phone: str | None = None) -> float:
    """提交火山成功后立即预扣费。重复（recovery）不再扣。返回预扣金额（重复时 0）。"""
    if already_precharged(db, task_id, provider_job_id):
        return 0.0
    api = "video.generate.a" if request_type in ("compose", "a_generate") else "video.remix.b"
    amount = estimate_cost(api, duration, resolution)
    _add(db, task_id=task_id, provider_job_id=provider_job_id, tenant_id=tenant_id,
         user_phone=user_phone, model=model, resolution=resolution, duration_seconds=duration,
         request_type=request_type, precharged_amount=amount, event_type="precharge", status="ok")
    return amount


def refund(db: Session, task_id: str, reason: str = "failed") -> float:
    """任务失败/取消 → 退回已预扣金额。返回退回总额。"""
    pres = db.query(CostLedger).filter(CostLedger.task_id == task_id,
                                       CostLedger.event_type == "precharge").all()
    refunded = db.query(CostLedger).filter(CostLedger.task_id == task_id,
                                           CostLedger.event_type == "refund").first()
    if refunded is not None:
        return 0.0
    total = sum(p.precharged_amount or 0.0 for p in pres)
    if total <= 0:
        return 0.0
    p0 = pres[0]
    _add(db, task_id=task_id, provider_job_id=p0.provider_job_id, tenant_id=p0.tenant_id,
         user_phone=p0.user_phone, model=p0.model, resolution=p0.resolution,
         duration_seconds=p0.duration_seconds, request_type=p0.request_type,
         actual_amount=-total, event_type="refund", status=reason)
    return total


def final_adjust(db: Session, task_id: str, actual_amount: float) -> CostLedger:
    """成片完成后按真实时长对账（actual_amount）。"""
    pres = db.query(CostLedger).filter(CostLedger.task_id == task_id,
                                       CostLedger.event_type == "precharge").first()
    return _add(
        db, task_id=task_id,
        provider_job_id=pres.provider_job_id if pres else None,
        tenant_id=pres.tenant_id if pres else "",
        request_type=pres.request_type if pres else None,
        actual_amount=actual_amount, event_type="final_adjust", status="ok",
    )


def net_charged(db: Session, tenant_id: str) -> float:
    """该租户净扣费（precharge - refund + final_adjust）。"""
    rows = db.query(CostLedger).filter(CostLedger.tenant_id == tenant_id).all()
    return round(sum((r.precharged_amount or 0.0) + (r.actual_amount or 0.0) for r in rows), 2)
